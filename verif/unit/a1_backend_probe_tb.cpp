#include "Va1_backend_probe.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

class ProbeTest {
public:
    Va1_backend_probe dut;
    std::array<unsigned, 32> sources{};
    std::array<uint32_t, 64> registers{};
    unsigned cases = 0;

    ProbeTest() {
        dut.clk_i = 0;
        dut.rst_i = 0;
        dut.flush_i = 0;
        dut.free_i = 0;
        dut.valid_i = 0;
        dut.ready_i = 0;
        dut.eligible_i = 0;
        dut.port_ready_i = 0;
        dut.wb_accept_i = 0;
        dut.wb_addr_i = 0;
        dut.wb_data_i = 0;
    }

    void require(bool condition, const std::string& message) {
        if (!condition) throw std::runtime_error(message + " case=" + std::to_string(cases));
    }

    void step() {
        ++cases;
        for (unsigned word = 0; word < 6; ++word) dut.source_i[word] = 0;
        for (unsigned operand = 0; operand < 32; ++operand) {
            for (unsigned bit = 0; bit < 6; ++bit) {
                unsigned position = operand * 6 + bit;
                dut.source_i[position / 32] |= ((sources[operand] >> bit) & 1) << (position % 32);
            }
        }
        const bool stop = dut.rst_i || dut.flush_i;
        auto visible = registers;
        for (unsigned lane = 0; lane < 2; ++lane) {
            unsigned address = (dut.wb_addr_i >> (lane * 6)) & 63;
            if (!stop && ((dut.wb_accept_i >> lane) & 1) && address)
                visible[address] = uint32_t(dut.wb_data_i >> (lane * 32));
        }

        std::vector<unsigned> free;
        for (unsigned reg = 1; reg < 64; ++reg)
            if (!stop && ((dut.free_i >> reg) & 1)) free.push_back(reg);
        unsigned expected_valid = free.empty() ? 0 : free.size() == 1 ? 1 : 3;
        unsigned expected_alloc = free.empty() ? 0 : free[0];
        if (free.size() > 1) expected_alloc |= free[1] << 6;

        std::array<int, 2> selected{-1, -1};
        for (unsigned lane = 0; lane < 2; ++lane) {
            if (stop || !((dut.port_ready_i >> lane) & 1)) continue;
            for (unsigned entry = 0; entry < 16; ++entry) {
                if (selected[0] == int(entry) || !((dut.valid_i >> entry) & 1)
                    || !((dut.eligible_i >> (lane * 16 + entry)) & 1)) continue;
                bool ready = true;
                for (unsigned operand = 0; operand < 2; ++operand) {
                    unsigned tag = sources[entry * 2 + operand];
                    bool available = !tag || ((dut.ready_i >> (entry * 2 + operand)) & 1);
                    for (unsigned wb = 0; wb < 2; ++wb)
                        if (((dut.wb_accept_i >> wb) & 1) && tag == ((dut.wb_addr_i >> (wb * 6)) & 63))
                            available = true;
                    ready &= available;
                }
                if (ready) {
                    selected[lane] = int(entry);
                    break;
                }
            }
        }
        uint32_t expected_grant = 0;
        unsigned expected_reads = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            if (selected[lane] < 0) continue;
            expected_grant |= 1u << (lane * 16 + selected[lane]);
            for (unsigned operand = 0; operand < 2; ++operand)
                expected_reads |= sources[selected[lane] * 2 + operand] << ((lane * 2 + operand) * 6);
        }
        dut.eval();
        require(dut.alloc_valid_o == expected_valid && dut.alloc_addr_o == expected_alloc, "allocator mismatch");
        require(dut.grant_o == expected_grant, "grant mismatch");
        require(dut.read_addr_o == expected_reads, "source mux mismatch");
        for (unsigned port = 0; port < 4; ++port)
            require(dut.read_data_o[port] == visible[(expected_reads >> (port * 6)) & 63], "PRF read mismatch");
        dut.clk_i = 1;
        dut.eval();
        registers = visible;
        dut.clk_i = 0;
        dut.eval();
    }
};

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        const uint32_t seed = argc > 1 ? std::stoul(argv[1]) : 1;
        std::mt19937 random(seed);
        ProbeTest tb;
        auto& dut = tb.dut;
        for (unsigned reg = 1; reg < 64; ++reg) {
            dut.wb_accept_i = 1;
            dut.wb_addr_i = reg;
            dut.wb_data_i = random();
            tb.step();
        }
        dut.wb_accept_i = 0;

        // Enumerate zero, singleton, and every two-candidate allocation bitmap, including p0.
        tb.step();
        for (unsigned first = 0; first < 64; ++first) {
            for (unsigned second = 0; second < 64; ++second) {
                dut.free_i = (uint64_t(1) << first) | (uint64_t(1) << second);
                tb.step();
            }
        }
        dut.free_i = ~uint64_t(0);
        dut.ready_i = 0xffffffff;
        dut.eligible_i = 0xffffffff;
        for (unsigned operand = 0; operand < 32; ++operand) tb.sources[operand] = operand + 1;
        for (unsigned ports = 0; ports < 4; ++ports) {
            dut.port_ready_i = ports;
            for (unsigned valid = 0; valid < 65536; ++valid) {
                dut.valid_i = valid;
                tb.step();
            }
        }

        // Wake both operands from either accepted write lane; exercise every issue slot and port.
        dut.ready_i = 0;
        for (unsigned entry = 0; entry < 16; ++entry) {
            dut.valid_i = 1u << entry;
            for (unsigned ports = 0; ports < 4; ++ports) {
                dut.port_ready_i = ports;
                for (unsigned swapped = 0; swapped < 2; ++swapped) {
                    unsigned first = tb.sources[entry * 2 + swapped];
                    unsigned second = tb.sources[entry * 2 + 1 - swapped];
                    dut.wb_addr_i = first | (second << 6);
                    for (unsigned accepted = 0; accepted < 4; ++accepted) {
                        dut.wb_accept_i = accepted;
                        dut.wb_data_i = (uint64_t(random()) << 32) | random();
                        tb.step();
                    }
                }
            }
        }
        dut.valid_i = 1;
        dut.port_ready_i = 3;
        dut.wb_accept_i = 3;
        dut.wb_addr_i = 0;
        dut.wb_data_i = ~uint64_t(0);
        tb.sources.fill(0);
        tb.step();

        // Suppressed writeback must leave stored payload unchanged after reset or flush.
        tb.sources[0] = 1;
        tb.sources[1] = 2;
        dut.ready_i = 3;
        dut.wb_addr_i = 1 | (2 << 6);
        for (unsigned control = 1; control < 4; ++control) {
            dut.wb_accept_i = 3;
            dut.rst_i = control & 1;
            dut.flush_i = (control >> 1) & 1;
            tb.step();
            dut.rst_i = 0;
            dut.flush_i = 0;
            dut.wb_accept_i = 0;
            tb.step();
        }
        for (unsigned iteration = 0; iteration < 10000; ++iteration) {
            dut.free_i = (uint64_t(random()) << 32) | random();
            dut.valid_i = random() & 65535;
            dut.ready_i = random();
            dut.eligible_i = random();
            dut.port_ready_i = random() & 3;
            dut.wb_accept_i = random() & 3;
            unsigned first = random() % 64;
            unsigned second = (first + 1 + random() % 63) % 64;
            dut.wb_addr_i = first | (second << 6);
            dut.wb_data_i = (uint64_t(random()) << 32) | random();
            for (auto& source : tb.sources) source = random() % 64;
            dut.rst_i = iteration % 37 == 0;
            dut.flush_i = iteration % 19 == 0;
            tb.step();
        }
        std::cout << "A1 PROBE PASS seed=" << seed << " cases=" << tb.cases << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
