#include "Vprf_4r2w.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

struct Write {
    bool accepted = false;
    unsigned address = 0;
    uint32_t value = 0;
};

using Writes = std::array<Write, 2>;
using Reads = std::array<unsigned, 4>;

class Scoreboard {
    Vprf_4r2w dut;
    std::array<uint32_t, 64> values{};
    std::array<bool, 64> known{};
    unsigned cycles = 0;
    unsigned checked_reads = 0;
    std::array<unsigned, 8> bypass_hits{};

    void check(const Reads& reads, const std::array<uint32_t, 64>& expected,
               const std::array<bool, 64>& valid, const char* phase) {
        for (unsigned port = 0; port < reads.size(); ++port) {
            if (!valid[reads[port]]) continue;
            ++checked_reads;
            if (dut.rdata_o[port] != expected[reads[port]]) {
                throw std::runtime_error(
                    std::string(phase) + " mismatch at cycle " + std::to_string(cycles)
                    + ", read port " + std::to_string(port)
                    + ", p" + std::to_string(reads[port]));
            }
        }
    }

public:
    Scoreboard() {
        known[0] = true;
        dut.clk_i = 0;
        dut.rst_i = 0;
        dut.wb_accept_i = 0;
        dut.raddr_i = 0;
        dut.waddr_i = 0;
        dut.wdata_i = 0;
    }

    void cycle(const Writes& writes, const Reads& reads, bool reset = false) {
        ++cycles;
        dut.clk_i = 0;
        dut.rst_i = reset;
        dut.wb_accept_i = 0;
        dut.waddr_i = 0;
        dut.wdata_i = 0;
        dut.raddr_i = 0;
        auto next_values = values;
        auto next_known = known;
        for (unsigned lane = 0; lane < writes.size(); ++lane) {
            const auto& write = writes[lane];
            dut.wb_accept_i |= unsigned(write.accepted) << lane;
            dut.waddr_i |= write.address << (lane * 6);
            dut.wdata_i |= uint64_t(write.value) << (lane * 32);
            if (!reset && write.accepted && write.address != 0) {
                next_values[write.address] = write.value;
                next_known[write.address] = true;
                for (unsigned port = 0; port < reads.size(); ++port) {
                    if (reads[port] == write.address) ++bypass_hits[port * 2 + lane];
                }
            }
        }
        for (unsigned port = 0; port < reads.size(); ++port)
            dut.raddr_i |= reads[port] << (port * 6);
        dut.eval();
        check(reads, next_values, next_known, "bypass");

        dut.clk_i = 1;
        dut.eval();
        values = next_values;
        known = next_known;
        dut.clk_i = 0;
        dut.wb_accept_i = 0;
        dut.wdata_i = ~dut.wdata_i;
        dut.eval();
        check(reads, values, known, "stored");
    }

    void scan() {
        for (unsigned address = 0; address < 64; address += 4)
            cycle({}, {address, address + 1, address + 2, address + 3});
    }

    void duplicate_write() {
        dut.rst_i = 0;
        dut.wb_accept_i = 3;
        dut.waddr_i = 7 | (7 << 6);
        dut.wdata_i = 0x8765432112345678ULL;
        dut.eval();
        dut.clk_i = 1;
        dut.eval();
        throw std::runtime_error("duplicate write did not trigger the ownership assertion");
    }

    void report(uint32_t seed) {
        for (unsigned hits : bypass_hits) {
            if (hits == 0) throw std::runtime_error("uncovered read/write bypass pair");
        }
        std::cout << "PRF PASS seed=" << seed << " cycles=" << cycles
                  << " reads=" << checked_reads << " bypass_pairs=8/8\n";
    }
};

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        Scoreboard tb;
        if (argc > 1 && std::string(argv[1]) == "--duplicate-write") {
            tb.duplicate_write();
            return 1;
        }
        const uint32_t seed = argc > 1 ? std::stoul(argv[1]) : 1;
        std::mt19937 random(seed);

        tb.cycle({Write{true, 0, 0xffffffff}, Write{true, 0, 0x12345678}}, {0, 0, 0, 0});
        tb.cycle({Write{true, 7, 1}, Write{true, 7, 2}}, {0, 0, 0, 0}, true);

        // Exhaust both write lanes, all addresses, and all eight forwarding paths.
        for (unsigned lane = 0; lane < 2; ++lane) {
            for (unsigned address = 1; address < 64; ++address) {
                Writes writes{};
                writes[lane] = {true, address, uint32_t(random())};
                tb.cycle(writes, {address, address, address, address});
            }
            tb.scan();
        }

        // Every ordered pair exercises independent simultaneous writes and read muxes.
        for (unsigned first = 0; first < 64; ++first) {
            for (unsigned second = 0; second < 64; ++second) {
                if (first == second && first != 0) continue;
                tb.cycle({Write{true, first, uint32_t(random())},
                          Write{true, second, uint32_t(random())}},
                         {first, second, first, second});
            }
        }
        tb.scan();

        // Disabled data must neither bypass nor persist; reset also suppresses collisions.
        for (unsigned address = 1; address < 64; ++address) {
            const Writes same = {Write{false, address, uint32_t(random())},
                                 Write{false, address, uint32_t(random())}};
            tb.cycle(same, {address, address, address, address});
            for (unsigned lane = 0; lane < 2; ++lane) {
                auto one_write = same;
                one_write[lane].accepted = true;
                tb.cycle(one_write, {address, address, address, address});
            }
            auto reset_writes = same;
            reset_writes[0].accepted = true;
            reset_writes[1].accepted = true;
            tb.cycle(reset_writes, {address, address, address, address}, true);
        }
        tb.scan();

        for (unsigned iteration = 0; iteration < 10000; ++iteration) {
            Writes writes = {Write{bool(random() & 1), unsigned(random() % 64), uint32_t(random())},
                             Write{bool(random() & 1), unsigned(random() % 64), uint32_t(random())}};
            const bool reset = random() % 31 == 0;
            if (!reset && writes[0].accepted && writes[1].accepted
                && writes[0].address == writes[1].address && writes[0].address != 0)
                writes[1].accepted = false;
            Reads reads{};
            for (auto& address : reads) address = random() % 64;
            tb.cycle(writes, reads, reset);
            if (iteration % 97 == 0) tb.scan();
        }
        tb.scan();
        tb.report(seed);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
