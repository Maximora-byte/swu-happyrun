// Independent C++ literal fixture. No debugger linkage or native API invocation.
#include "scripts/diagnostics/issue110_filter_capsule.hpp"
#include <cassert>
#include <iostream>
#include <string>
#include <stdexcept>

using namespace issue110_filter_capsule;

class MemorySink final : public ByteSink {
public:
    std::string bytes;
    std::size_t fail_at = kCapsuleLimit;
    std::size_t calls = 0;
    bool append(const char* data, std::size_t size) override {
        ++calls;
        if (size > fail_at - bytes.size()) return false;
        bytes.append(data, size);
        return true;
    }
};

class PartialSink final : public ByteSink {
public:
    std::string bytes;
    std::size_t calls = 0;
    bool throws = false, partial = false;
    bool append(const char* data, std::size_t size) override {
        ++calls;
        if (calls == 4) {
            if (partial) bytes.append(data, size / 2);
            if (throws) throw std::runtime_error("private write failure");
            return false;
        }
        bytes.append(data, size);
        return true;
    }
};

int main(int argc, char**) {
    CapsuleInput input;
    input.nonce = "0123456789abcdef0123456789abcdef";
    input.child_pid = 4242;
    const std::string golden =
        R"({"schema":"swu.issue110.filter-capsule.v1","mode":"fixed_no_target","nonce":"0123456789abcdef0123456789abcdef","child_pid":4242,"stage":"not_started","issue":"none","engine_creation_attempted":false,"observations_complete":false,"getter_a":{"valid":false,"hresult":null,"reported_length":null,"bytes_hex":""},"getter_b":{"valid":false,"hresult":null,"reported_length":null,"bytes_hex":""},"sx":{"bytes_hex":"","overflow":false,"association":"not_observed"},"a_expected":"not_observed","b_expected":"not_observed","ab_stability":"not_observed","hresult_trace":[],"module_paths_utf16le_hex":[],"release":{"all_owned_release_calls_issued":false,"engine_disposal_confirmed":false,"detach_hresult":null,"control_release_return":null,"client_release_return":null,"callback_release_return":null,"wrong_thread":false,"callback_violation":false}})";
    MemorySink sink;
    auto result = encode_capsule(input, sink);
    assert(result.complete && result.error == EncodeError::none);
    assert(result.bytes_written == sink.bytes.size());
    assert(sink.bytes.substr(0, 10) == "SWU110FP1\n");
    assert(sink.bytes.substr(19, golden.size()) == golden);
    assert(sink.bytes.size() == golden.size() + 30);
    assert(sink.bytes.substr(sink.bytes.size() - 11) == "\nSWU110END\n");
    assert(std::stoul(sink.bytes.substr(10, 8), nullptr, 16) == golden.size());
    const auto valid = sink.bytes;
    // An invalid getter does not authorize serializing a supplied scratch tail.
    input.getter_a.bytes = "SENTINEL_CANARY";
    sink.bytes.clear();
    result = encode_capsule(input, sink);
    assert(!result.complete && result.error == EncodeError::invalid_input && sink.bytes.empty());
    input.getter_a = {};
    input.getter_a.valid = true;
    input.getter_a.hresult = 0;
    std::string maximum_getter(4095, 'A');
    maximum_getter += '\0';
    input.getter_a.bytes = maximum_getter;
    input.getter_a.reported_length = 4096;
    input.a_expected = Comparison::different;
    sink.bytes.clear();
    assert(encode_capsule(input, sink).complete);
    maximum_getter += '\0';
    input.getter_a.bytes = maximum_getter;
    input.getter_a.reported_length = 4097;
    sink.bytes.clear();
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    input = {};
    input.nonce = "0123456789abcdef0123456789abcdef";
    input.child_pid = 4242;
    std::string maximum_output(65536, '\xff');
    input.sx.bytes = maximum_output;
    sink.bytes.clear();
    assert(encode_capsule(input, sink).complete);
    maximum_output += 'A';
    input.sx.bytes = maximum_output;
    sink.bytes.clear();
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    input.sx.bytes = {};
    input.nonce = "BAD";
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    input.nonce = "0123456789abcdef0123456789abcdef";
    input.child_pid = 0;
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    input.child_pid = 4242;
    input.stage = static_cast<Stage>(999);
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    input.stage = Stage::not_started;
    // Worst-case private path data is bounded, but still cannot exceed the total cap.
    std::string path(8192, 'A');
    for (auto& entry : input.module_paths_utf16le) entry = path;
    input.module_path_count = input.module_paths_utf16le.size();
    result = encode_capsule(input, sink);
    assert(!result.complete && result.error == EncodeError::too_large && sink.bytes.empty());
    input.module_path_count = 0;
    for (std::size_t offset = 0; offset < valid.size(); ++offset) {
        MemorySink fail;
        fail.fail_at = offset;
        result = encode_capsule(input, fail);
        assert(!result.complete && result.error == EncodeError::sink_failure);
        assert(result.bytes_written == fail.bytes.size());
        assert(fail.bytes.size() < valid.size());
    }
    // C2: exceptions and prefix writes are terminal, never retried. The
    // confirmed header is independently 10 magic + 8 length + 1 newline bytes.
    for (const bool throws : {false, true}) {
        for (const bool partial : {false, true}) {
            PartialSink failed;
            failed.throws = throws;
            failed.partial = partial;
            result = encode_capsule(input, failed);
            assert(!result.complete && result.error == EncodeError::sink_failure);
            assert(result.bytes_written == 19 && failed.calls == 4);
            assert(failed.bytes.size() == 19 + (partial ? 38 : 0));
        }
    }
    // C1: literal fixed-size inputs, not a size found by querying the encoder.
    // 65536 sx bytes, seven 8192-byte paths, one 7746-byte path and 5/6/7-digit
    // PIDs independently yield total frames 262143/262144/262145 respectively.
    std::string boundaries;
    std::string sx_boundary(65536, 'A'), path_boundary(8192, 'A'), last_path(7746, 'A');
    input.sx.bytes = sx_boundary;
    input.module_path_count = 8;
    for (std::size_t index = 0; index < 7; ++index)
        input.module_paths_utf16le[index] = path_boundary;
    input.module_paths_utf16le[7] = last_path;
    const std::uint32_t pids[] = {42424, 424242, 4242424};
    for (std::size_t index = 0; index < 3; ++index) {
        input.child_pid = pids[index];
        MemorySink boundary;
        result = encode_capsule(input, boundary);
        if (index < 2) {
            assert(result.complete && boundary.bytes.size() == 262143 + index);
            boundaries += boundary.bytes;
        } else {
            assert(!result.complete && result.error == EncodeError::too_large);
            assert(boundary.calls == 0 && boundary.bytes.empty() && result.bytes_written == 0);
        }
    }
    input = {};
    input.nonce = "0123456789abcdef0123456789abcdef";
    input.child_pid = 4242;
    // Complete means the existing core's detach/output conditions also hold.
    constexpr char command[] = "$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb";
    input.getter_a = {true, 0, sizeof(command), std::string_view(command, sizeof(command))};
    input.getter_b = input.getter_a;
    input.a_expected = input.b_expected = input.ab_stability = Comparison::equal;
    input.stage = Stage::observations_complete;
    input.observations_complete = input.engine_creation_attempted = true;
    input.sx = {"display\n", false, Association::associated};
    input.release.all_owned_release_calls_issued = true;
    sink.bytes.clear();
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    input.release.detach_hresult = 0;
    assert(encode_capsule(input, sink).complete);
    input.sx.bytes = "\xff";
    sink.bytes.clear();
    assert(!encode_capsule(input, sink).complete && sink.bytes.empty());
    std::cout << (argc > 1 ? boundaries : valid);
}
