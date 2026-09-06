#include "Vsingle_lane_core.h"
#include "verilated.h"
#include "fields.hpp"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
template<class T> uint32_t get(const T& data, unsigned offset, unsigned width) {
    uint32_t result = 0;
    for (unsigned i = 0; i < width; ++i) result |= ((data[(offset+i)/32] >> ((offset+i)%32)) & 1u) << i;
    return result;
}
template<class T> void put(T& data, unsigned offset, unsigned width, uint32_t value) {
    for (unsigned i = 0; i < width; ++i) {
        uint32_t mask = 1u << ((offset+i)%32);
        data[(offset+i)/32] = (data[(offset+i)/32] & ~mask) | (((value >> i) & 1u) ? mask : 0);
    }
}
struct Transaction {
    bool pending = false, write = false, uncached = false;
    unsigned delay = 0, id = 0, address = 0, mask = 0, size = 0;
    std::array<uint32_t,8> words{};
};
int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    try {
        require(argc >= 4, "image, seed, and event count required");
        std::ifstream file(argv[1], std::ios::binary);
        require(bool(file), "cannot open program");
        std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
        require(image.size() <= 65536, "program exceeds BRAM");
        image.resize(65536);
        auto memory = image;
        std::array<uint8_t,48> mmio{};
        std::mt19937 random(std::stoul(argv[2]));
        unsigned target = std::stoul(argv[3]);
        std::string mode = argc > 4 ? argv[4] : "normal";
        Vsingle_lane_core dut;
        Transaction instruction, data;
        unsigned events = 0, cycle = 0, first_valid = 0, committed_stores = 0;
        unsigned store_stall = 0;
        bool reset_done = false, holding_event = false, hold_i = false, hold_d = false;
        std::array<uint32_t,COMMIT_WORDS> held_event{};
        std::array<uint32_t,REQUEST_WORDS> held_i{}, held_d{};
        auto byte = [&](unsigned address) -> uint8_t& {
            if (address < memory.size()) return memory[address];
            if (address >= 0x10000000 && address < 0x10000010) return mmio[address - 0x10000000];
            if (address >= 0x10001000 && address < 0x10001020) return mmio[16 + address - 0x10001000];
            throw std::runtime_error("request outside PMA");
        };
        auto drive_response = [&](Transaction& tx, auto& response, bool is_data) {
            for (unsigned i = 0; i < RESPONSE_WORDS; ++i) response[i] = 0;
            if (!tx.pending || tx.delay) return;
            unsigned status = 0;
            if (is_data && tx.address == 0x900 && mode == "load_fault") status = 1;
            if (!is_data && tx.address == 0x300 && mode == "fetch_fault") status = 1;
            if (is_data && tx.write && mode == "store_fault") status = 1;
            if (is_data && mode == "protocol_error") status = 2;
            if (is_data && mode == "reserved_status") status = 3;
            put(response, RSP_TRANSACTION_ID, 4, tx.id ^ ((is_data && mode == "wrong_id") || (!is_data && mode == "fetch_wrong_id") ? 1u : 0u));
            put(response, RSP_STATUS, 2, status);
            if (!tx.write && status == 0) {
                unsigned base = tx.uncached ? tx.address & ~3u : tx.address;
                for (unsigned word = 0; word < (tx.uncached ? 1u : 8u); ++word) {
                    uint32_t value = 0;
                    for (unsigned lane = 0; lane < 4; ++lane) value |= uint32_t(byte(base+word*4+lane)) << (lane*8);
                    if (tx.uncached) {
                        uint32_t selected = (tx.size == 2 ? 0xffffffffu : (1u << (8u << tx.size))-1) << (8*(tx.address & 3));
                        value &= selected;
                    }
                    put(response, (tx.uncached ? RSP_UNCACHED_READ_DATA : RSP_LINE_READ_DATA) + word*32, 32, value);
                }
            }
            if ((is_data && mode == "payload_error") || (!is_data && mode == "fetch_payload"))
                put(response, RSP_UNCACHED_READ_DATA, 32, 1);
        };
        auto accept = [&](Transaction& tx, const auto& request, bool is_data) {
            require(!tx.pending, "request reused an occupied slot");
            tx.pending = true;
            tx.delay = 1 + random()%7;
            tx.id = get(request, REQ_TRANSACTION_ID, 4);
            tx.address = get(request, REQ_ADDRESS, 32);
            tx.uncached = get(request, REQ_UNCACHED, 1);
            tx.write = get(request, REQ_WRITE, 1);
            tx.size = get(request, REQ_UNCACHED_SIZE, 2);
            std::cout << (is_data ? "DREQ" : "IREQ");
            for (unsigned w = 0; w < REQUEST_WORDS; ++w) std::cout << ' ' << std::hex << request[w];
            std::cout << std::dec << '\n';
            require(is_data || (!tx.write && !tx.uncached), "invalid instruction request");
            require(tx.uncached || !(tx.address & 31), "unaligned line request");
            tx.mask = get(request, tx.uncached ? REQ_UNCACHED_WRITE_STROBE : REQ_LINE_WRITE_MASK, tx.uncached ? 4 : 32);
            for (unsigned w = 0; w < (tx.uncached ? 1u : 8u); ++w)
                tx.words[w] = get(request, (tx.uncached ? REQ_UNCACHED_WRITE_DATA : REQ_LINE_WRITE_DATA)+w*32, 32);
            if (tx.write) {
                require(committed_stores > 0, "store escaped before retirement");
                --committed_stores;
                unsigned base = tx.uncached ? tx.address & ~3u : tx.address;
                if (mode != "store_fault") for (unsigned lane = 0; lane < (tx.uncached ? 4u : 32u); ++lane)
                    if ((tx.mask >> lane) & 1) byte(base+lane) = uint8_t(tx.words[lane/4] >> ((lane%4)*8));
            }
        };
        auto reset = [&]() {
            instruction = {}; data = {};
            memory = image; mmio.fill(0);
            events = 0; committed_stores = 0; holding_event = false; hold_i = false; hold_d = false;
            dut.rst_i = 1; dut.instruction_response_valid_i = 0; dut.data_response_valid_i = 0;
            dut.instruction_request_ready_i = 0; dut.data_request_ready_i = 0; dut.commit_ready_i = 0;
            for (int i = 0; i < 3; ++i) { dut.clk_i = 0; dut.eval(); dut.clk_i = 1; dut.eval(); }
            dut.rst_i = 0;
            std::cout << "RESET\n";
        };
        reset();
        for (cycle = 0; cycle < target*100 + 2000; ++cycle) {
            dut.clk_i = 0;
            dut.instruction_request_ready_i = random()%4 != 0;
            dut.data_request_ready_i = random()%4 != 0;
            dut.commit_ready_i = random()%3 != 0;
            if (mode == "reset_commit" && !reset_done) dut.commit_ready_i = 0;
            drive_response(instruction, dut.instruction_response_i, false);
            drive_response(data, dut.data_response_i, true);
            dut.instruction_response_valid_i = instruction.pending && !instruction.delay;
            dut.data_response_valid_i = data.pending && !data.delay;
            if (mode == "unsolicited" && cycle == 2) dut.data_response_valid_i = 1;
            dut.eval();
            if (mode == "stall_store" && get(dut.commit_o, EV_VALID, 1) && get(dut.commit_o, EV_MEM_WRITE_MASK, 4)) {
                dut.commit_ready_i = store_stall >= 8;
                ++store_stall;
                dut.eval();
            } else store_stall = 0;
            if (!reset_done && ((mode == "reset_fetch" && instruction.pending)
                || (mode == "reset_data" && data.pending)
                || (mode == "reset_commit" && get(dut.commit_o, EV_VALID, 1)))) {
                reset(); reset_done = true; continue;
            }
            auto hold = [&](const auto& bus, auto& snapshot, bool& held, bool valid, bool ready) {
                if (held) {
                    require(valid, "valid dropped under backpressure");
                    for (unsigned i = 0; i < snapshot.size(); ++i) require(snapshot[i] == bus[i], "payload changed under backpressure");
                }
                held = valid && !ready;
                for (unsigned i = 0; i < snapshot.size(); ++i) snapshot[i] = bus[i];
            };
            hold(dut.instruction_request_o, held_i, hold_i, dut.instruction_request_valid_o, dut.instruction_request_ready_i);
            hold(dut.data_request_o, held_d, hold_d, dut.data_request_valid_o, dut.data_request_ready_i);
            bool valid = get(dut.commit_o, EV_VALID, 1);
            require(!get(dut.commit_o, EVENT_BITS + EV_VALID, 1), "second retirement lane active");
            if (valid && !holding_event) first_valid = cycle;
            hold(dut.commit_o, held_event, holding_event, valid, dut.commit_ready_i);
            if (valid && dut.commit_ready_i) {
                if (get(dut.commit_o, EV_MEM_WRITE_MASK, 4)) ++committed_stores;
                std::cout << "EVENT " << std::dec << cycle << ' ' << first_valid;
                for (unsigned i = 0; i < COMMIT_WORDS; ++i) std::cout << ' ' << std::hex << dut.commit_o[i];
                std::cout << std::dec << '\n';
                ++events;
            }
            if (dut.instruction_response_valid_i && dut.instruction_response_ready_o) {
                std::cout << "IRSP";
                for (unsigned w = 0; w < RESPONSE_WORDS; ++w) std::cout << ' ' << std::hex << dut.instruction_response_i[w];
                std::cout << std::dec << '\n';
                instruction.pending = false;
            }
            if (dut.data_response_valid_i && dut.data_response_ready_o) {
                std::cout << "DRSP";
                for (unsigned w = 0; w < RESPONSE_WORDS; ++w) std::cout << ' ' << std::hex << dut.data_response_i[w];
                std::cout << std::dec << '\n';
                data.pending = false;
            }
            if (instruction.pending && instruction.delay) --instruction.delay;
            if (data.pending && data.delay) --data.delay;
            if (dut.instruction_request_valid_o && dut.instruction_request_ready_i) accept(instruction, dut.instruction_request_o, false);
            if (dut.data_request_valid_o && dut.data_request_ready_i) accept(data, dut.data_request_o, true);
            dut.clk_i = 1; dut.eval();
            if (dut.platform_fatal_o) {
                for (int wait = 0; wait < 8; ++wait) {
                    dut.clk_i = 0; dut.eval();
                    require(!dut.instruction_request_valid_o && !dut.data_request_valid_o && !get(dut.commit_o, EV_VALID, 1), "activity after fatal");
                    dut.clk_i = 1; dut.eval();
                    require(dut.platform_fatal_o, "fatal is not sticky");
                }
                std::cout << "FATAL " << events << '\n';
                return 0;
            }
            if (events >= target) {
                require(!(mode.rfind("reset_", 0) == 0) || reset_done, "reset scenario did not fire");
                std::cout << "CORE PASS events=" << events << " cycles=" << cycle+1 << '\n';
                return 0;
            }
        }
        throw std::runtime_error("watchdog expired");
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
