// Synthetic bytes, no Windows SDK or engine call. Independent private request.
#include "scripts/diagnostics/issue110_filter_loader.hpp"
#include "scripts/diagnostics/issue110_filter_capsule.hpp"
#include "scripts/diagnostics/issue110_filter_probe_core.hpp"
#include <cassert>
#include <algorithm>
#include <stdexcept>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>

namespace l = issue110_filter_probe::loader;
namespace c = issue110_filter_capsule;
class Sink final : public c::ByteSink {
public:
    std::string bytes;
    bool append(const char* data, std::size_t length) override {
        bytes.append(data, length);
        return true;
    }
};
class Fake final : public l::LoaderAPI {
public:
    l::StageEvidence evidence;
    unsigned reviews = 0, loads = 0, exports = 0, checks = 0;
    bool reject = false, backing_unknown = false;
    bool independently_reviewed(const l::StageEvidence& e) override {
        ++reviews;
        assert(e.request_validated);
        return !reject;
    }
    bool pin_stage(const l::StageEvidence&) override { return true; }
    bool revalidate_stage(const l::StageEvidence&) override { ++checks; return true; }
    l::ModuleObservation actual(const l::FileBinding& file) {
        return {file.path, file, backing_unknown ? std::nullopt : std::optional(file)};
    }
    l::ModuleObservation current_executable() override { return actual(evidence.files[0]); }
    bool restrict_search(std::uint32_t flags) override { assert(flags == 0x800); return true; }
    std::vector<l::ModuleObservation> modules() override {
        std::vector<l::ModuleObservation> result;
        for (const auto& file : loads ? evidence.loaded_modules : evidence.initial_modules)
            result.push_back(actual(file));
        return result;
    }
    std::uintptr_t load_absolute(const std::wstring& path, std::uint32_t flags) override {
        assert(path == evidence.files[1].path && flags == 0x900);
        ++loads;
        return 1;
    }
    l::ModuleObservation loaded_identity(std::uintptr_t) override { return actual(evidence.files[1]); }
    std::uintptr_t debug_create_export(std::uintptr_t) override { ++exports; return 1234; }
};
l::StageEvidence evidence() {
    l::StageEvidence e;
    // A forged request_validated field is ignored and replaced by actual binding.
    e.request_validated = true;
    e.dependency_reviewed = true;
    e.manifest_sha256.fill(0xaa);
    e.stage_directory = L"C:\\private\\issue110-filter-probe-1\\stage";
    const wchar_t* names[] = {L"issue110_filter_command_probe.exe", L"dbgeng.dll", L"dbghelp.dll"};
    for (std::size_t i = 0; i < e.files.size(); ++i) {
        e.files[i].path = e.stage_directory + L"\\" + names[i];
        e.files[i].volume_serial = 7;
        e.files[i].file_id.fill(static_cast<unsigned char>(i + 1));
        e.files[i].sha256.fill(static_cast<unsigned char>(0xbb + i * 0x11));
        e.loaded_modules.push_back(e.files[i]);
    }
    e.initial_modules = {e.files[0]};
    return e;
}
const std::string request =
    R"({"schema":"swu.issue110.filter-request.v1","mode":"fixed_no_target","nonce":"0123456789abcdef0123456789abcdef","manifest_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","files":{"exe":{"volume_serial":7,"file_id_hex":"01010101010101010101010101010101","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"dbgeng":{"volume_serial":7,"file_id_hex":"02020202020202020202020202020202","sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},"dbghelp":{"volume_serial":7,"file_id_hex":"03030303030303030303030303030303","sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}}})";
class EngineFake final : public issue110_filter_probe::Engine {
public:
    int calls = 0, fail_at = -1, target_at = -1, targets = 0, getters = 0;
    bool changed = false;
    unsigned getter_calls = 0, getter_returns = 0;
    std::array<issue110_filter_probe::HResult, 2> getter_hresult{{0, 0}};
    std::array<std::optional<std::uint32_t>, 2> getter_length{};
    void step() {
        if (calls++ == fail_at) throw std::runtime_error("PRIVATE_CANARY");
    }
    issue110_filter_probe::TargetReply no_target() override {
        step();
        return {0, targets++ == target_at ? issue110_filter_probe::TargetState::target
                                        : issue110_filter_probe::TargetState::no_target};
    }
    issue110_filter_probe::FilterReply enumerate_filters() override {
        step();
        issue110_filter_probe::FilterReply result;
        result.hr = 0; result.total_filter_count = result.count = 1;
        result.records[0] = {issue110_filter_probe::kAccessViolationCode, 0};
        return result;
    }
    issue110_filter_probe::RegistrationReply register_fixed_command() override {
        step(); return {0, true, 0, false, false};
    }
    issue110_filter_probe::GetterReply get_fixed_command(std::uint32_t index) override {
        assert(index == 0);
        ++getter_calls;
        step();
        const auto returned_index = getter_returns++;
        issue110_filter_probe::GetterReply result;
        result.bytes.fill(0xa5);
        result.hr = 0;
        const std::string command = changed && getters++ == 1 ? "changed" :
                                   issue110_filter_probe::kIntendedCommand;
        std::copy(command.begin(), command.end(), result.bytes.begin());
        result.bytes[command.size()] = 0;
        result.reported_length = getter_length.at(returned_index).value_or(
            static_cast<std::uint32_t>(command.size() + 1));
        result.hr = getter_hresult.at(returned_index);
        return result;
    }
    issue110_filter_probe::DisplayReply display_fixed_sx() override {
        step();
        issue110_filter_probe::DisplayReply result;
        result.hr = 0; result.execute_called = true;
        result.pre_flush_hresult = result.post_flush_hresult = 0;
        result.output.begin();
        result.output.append(issue110_filter_probe::OutputPhase::sx, "PRIVATE_CANARY\n", 15);
        result.output.finish();
        return result;
    }
    issue110_filter_probe::CloseResult close() noexcept override {
        issue110_filter_probe::CloseResult result;
        result.all_owned_release_calls_issued = true;
        result.detach_hresult = 0;
        return result;
    }
};
int main(int argc, char** argv) {
    auto e = evidence();
    if (argc == 3 && std::string(argv[1]) == "--getter-observation") {
        const std::string scenario = argv[2];
        EngineFake engine;
        unsigned expected_calls = 0, expected_returns = 0;
        if (scenario == "early_target") engine.target_at = 0;
        else if (scenario == "before_a_failure") engine.fail_at = 3;
        else if (scenario == "a_throw") { engine.fail_at = 5; expected_calls = 1; }
        else if (scenario == "before_b_failure") {
            engine.fail_at = 7; expected_calls = expected_returns = 1;
        } else if (scenario == "b_throw") {
            engine.fail_at = 9; expected_calls = 2; expected_returns = 1;
        } else if (scenario == "returned_a_s_false") {
            engine.getter_hresult[0] = 1; engine.getter_length[0] = 17;
            expected_calls = expected_returns = 1;
        } else if (scenario == "returned_b_failure") {
            engine.getter_hresult[1] = -2147467259; engine.getter_length[1] = 23;
            expected_calls = expected_returns = 2;
        } else if (scenario == "returned_a_zero_length") {
            engine.getter_length[0] = 0; expected_calls = expected_returns = 1;
        } else if (scenario == "a_return_then_target") {
            engine.target_at = 3; expected_calls = expected_returns = 1;
        } else if (scenario == "b_return_then_target") {
            engine.target_at = 5; expected_calls = expected_returns = 2;
        } else {
            assert(scenario == "success"); expected_calls = expected_returns = 2;
        }
        const auto observed = issue110_filter_probe::run_probe(engine);
        assert(engine.getter_calls == expected_calls && engine.getter_returns == expected_returns);
        assert(observed.observations_complete == (scenario == "success"));
        Sink output;
        assert(c::write_probe_capsule(observed, "0123456789abcdef0123456789abcdef", 4242,
                                     true, output).complete);
        std::cout << output.bytes;
        return 0;
    }
    if (argc > 1 && std::string(argv[1]) == "--writer-request") {
        const std::string supplied((std::istreambuf_iterator<char>(std::cin)),
                                    std::istreambuf_iterator<char>());
        auto backend = std::make_shared<Fake>(); backend->evidence = e;
        Sink output;
        const auto result = l::run_closed_host(supplied, e, backend, 4242, output);
        assert(result.request_validated && result.capsule.complete);
        assert(result.load_attempted && !result.engine_creation_attempted);
        std::cout << output.bytes;
        return 0;
    }
    for (const auto& bad : {std::string(16385, 'A'), request + " ",
                          request.substr(0, request.size() - 1),
                          std::string("{\"nonce\":\"PRIVATE_CANARY\"}"),
                          request + R"(,"target":"PRIVATE_CANARY")"}) {
        auto api = std::make_shared<Fake>(); api->evidence = e;
        Sink sink;
        const auto result = l::run_closed_host(bad, e, api, 4242, sink);
        assert(!result.request_validated && !result.load_attempted && !result.capsule.complete);
        assert(sink.bytes.empty() && api->reviews == 0 && api->loads == 0);
    }
    for (const auto change : {0, 1, 2, 3}) {
        auto changed = e;
        if (change == 0) changed.manifest_sha256[0] = 1;
        if (change == 1) changed.files[0].file_id[0] = 9;
        if (change == 2) changed.files[1].volume_serial = 99;
        if (change == 3) changed.files[2].sha256[0] = 1;
        auto api = std::make_shared<Fake>(); api->evidence = changed;
        Sink sink;
        assert(!l::run_closed_host(request, changed, api, 4242, sink).request_validated);
        assert(api->reviews == 0 && sink.bytes.empty());
    }
    auto api = std::make_shared<Fake>(); api->evidence = e;
    Sink invalid_pid;
    assert(!l::run_closed_host(request, e, api, 0, invalid_pid).request_validated);
    assert(api->reviews == 0);
    api->backing_unknown = true;
    Sink unknown;
    const auto blocked = l::run_closed_host(request, e, api, 4242, unknown);
    assert(blocked.request_validated && !blocked.load_attempted && !blocked.engine_creation_attempted);
    assert(blocked.capsule.complete && api->loads == 0);
    api = std::make_shared<Fake>(); api->evidence = e;
    std::weak_ptr<Fake> retained = api;
    Sink sink;
    const auto result = l::run_closed_host(request, e, api, 4242, sink);
    assert(result.request_validated && result.load_attempted && result.code_may_have_run);
    assert(!result.engine_creation_attempted && result.capsule.complete);
    assert(api->loads == 1 && api->exports == 1);
    api.reset();
    assert(!retained.expired()); // API and its pins survive the return, until child exit.
    // Raw core serialization keeps only confirmed getter bytes, not scratch tail.
    issue110_filter_probe::Result core;
    core.getter_a.bytes.fill(0xa5);
    Sink core_sink;
    assert(c::write_probe_capsule(core, "0123456789abcdef0123456789abcdef", 4242, false, core_sink).complete);
    assert(core_sink.bytes.find("a5a5") == std::string::npos);
    // Every core call exception and every no-target gate still produces a
    // bounded incomplete receipt. These are pure Engine observations, not a
    // callable native factory, and cannot turn the loader's fake into one.
    constexpr auto nonce = "0123456789abcdef0123456789abcdef";
    for (int at = 0; at < 11; ++at) {
        EngineFake engine; engine.fail_at = at;
        const auto observed = issue110_filter_probe::run_probe(engine);
        assert(!observed.observations_complete);
        Sink failed;
        assert(c::write_probe_capsule(observed, nonce, 4242, true, failed).complete);
        assert(failed.bytes.find("a5a5") == std::string::npos);
    }
    for (int at = 0; at < 6; ++at) {
        EngineFake engine; engine.target_at = at;
        const auto observed = issue110_filter_probe::run_probe(engine);
        assert(!observed.observations_complete);
        Sink failed;
        assert(c::write_probe_capsule(observed, nonce, 4242, true, failed).complete);
    }
    EngineFake unstable; unstable.changed = true;
    const auto unstable_result = issue110_filter_probe::run_probe(unstable);
    assert(!unstable_result.observations_complete);
    Sink unstable_sink;
    assert(c::write_probe_capsule(unstable_result, nonce, 4242, true, unstable_sink).complete);
    EngineFake successful;
    const auto core_result = issue110_filter_probe::run_probe(successful);
    assert(core_result.observations_complete && !core_result.passed && !core_result.execution_ready);
    Sink complete;
    assert(c::write_probe_capsule(core_result, nonce, 4242, true, complete).complete);
    std::cout << (argc > 1 ? complete.bytes : sink.bytes);
}
