// Portable synthetic observations only. No Windows branches or engine code run.
#include "scripts/diagnostics/issue110_filter_loader.hpp"
#include <cassert>
#include <iostream>
#include <thread>
#include <type_traits>
using namespace issue110_filter_probe::loader;

static FileBinding file(const wchar_t* path, unsigned char n) {
    FileBinding value;
    value.path = path;
    value.volume_serial = 1;
    value.file_id[0] = n;
    value.sha256.fill(n);
    return value;
}
static StageEvidence evidence() {
    StageEvidence e;
    e.manifest_sha256.fill(1);
    e.request_validated = true;
    e.dependency_reviewed = true;
    e.stage_directory = L"C:\\private\\issue110-filter-probe-1\\stage";
    e.files = {file(L"C:\\private\\issue110-filter-probe-1\\stage\\issue110_filter_command_probe.exe", 1),
               file(L"C:\\private\\issue110-filter-probe-1\\stage\\dbgeng.dll", 2),
               file(L"C:\\private\\issue110-filter-probe-1\\stage\\dbghelp.dll", 3)};
    e.initial_modules = {e.files[0], file(L"C:\\Windows\\System32\\kernel32.dll", 4)};
    e.loaded_modules = e.initial_modules;
    e.loaded_modules.push_back(e.files[1]);
    e.loaded_modules.push_back(e.files[2]);
    return e;
}
static ModuleObservation observation(const FileBinding& binding) {
    // Synthetic association for portable policy tests, NOT Windows evidence.
    return {binding.path, binding, binding};
}
static unsigned arbitrary_factory_calls = 0;
static void arbitrary_factory() { ++arbitrary_factory_calls; }
class FakeLoader final : public LoaderAPI {
public:
    StageEvidence expected = evidence();
    bool approved = true, search = true, pin_ok = true, changed = false;
    bool unexpected_initial = false, unexpected_after = false, bad_actual = false;
    bool throws_load = false, missing_export = false;
    int unknown_mapping = -1, wrong_mapping = -1;
    unsigned pins = 0, search_calls = 0, loads = 0, exports = 0;
    bool independently_reviewed(const StageEvidence&) override { return approved; }
    bool pin_stage(const StageEvidence&) override { ++pins; return pin_ok; }
    bool revalidate_stage(const StageEvidence&) override { return !changed; }
    ModuleObservation observed(const FileBinding& file, int stage) {
        auto value = observation(file);
        if (unknown_mapping == stage) value.mapped_backing.reset();
        if (wrong_mapping == stage) value.mapped_backing->file_id[0] ^= 0x40;
        return value;
    }
    ModuleObservation current_executable() override { return observed(expected.files[0], 0); }
    bool restrict_search(std::uint32_t flags) override {
        assert(flags == 0x800); ++search_calls; return search;
    }
    std::vector<ModuleObservation> modules() override {
        auto values = loads ? expected.loaded_modules : expected.initial_modules;
        if ((!loads && unexpected_initial) || (loads && unexpected_after))
            values.push_back(file(L"C:\\bad.dll", 9));
        std::vector<ModuleObservation> result;
        for (const auto& value : values) result.push_back(observed(value, loads ? 3 : 1));
        return result;
    }
    std::uintptr_t load_absolute(const std::wstring& path, std::uint32_t flags) override {
        assert(path == expected.files[1].path);
        assert(flags == 0x900);
        ++loads;
        if (throws_load) throw 1;
        return 7;
    }
    ModuleObservation loaded_identity(std::uintptr_t module) override {
        assert(module == 7);
        auto actual = expected.files[1];
        if (bad_actual) actual.sha256[0] = 8;
        return observed(actual, 2);
    }
    std::uintptr_t debug_create_export(std::uintptr_t module) override {
        assert(module == 7); ++exports;
        return missing_export ? 0 : reinterpret_cast<std::uintptr_t>(&arbitrary_factory);
    }
};
int main() {
    static_assert(!std::is_copy_constructible_v<VerifiedEngineModule>);
    static_assert(!std::is_default_constructible_v<VerifiedEngineModule>);
    static_assert(std::is_move_constructible_v<VerifiedEngineModule>);
    static_assert(!std::is_constructible_v<VerifiedEngineModule, std::uintptr_t, std::uintptr_t>);
    static_assert(!std::is_constructible_v<VerifiedEngineModule, ModuleObservation>);
    { FakeLoader api; auto r = load_verified_engine(StageEvidence{}, api);
      assert(!r.module && !r.load_attempted && api.pins == 0); }
    for (int invalid = 0; invalid < 8; ++invalid) {
        FakeLoader api;
        auto e = evidence();
        if (invalid == 0) e.request_validated = false;
        if (invalid == 1) e.dependency_reviewed = false;
        if (invalid == 2) e.manifest_sha256.fill(0);
        if (invalid == 3) api.approved = false;
        if (invalid == 4) e.files[1].path = L"C:\\alias\\dbgeng.dll";
        if (invalid == 5) api.pin_ok = false;
        if (invalid == 6) api.changed = true;
        if (invalid == 7) e.files[1].sha256.fill(0);
        auto result = load_verified_engine(e, api);
        assert(!result.module && !result.load_attempted && api.loads == 0);
    }
    { FakeLoader api; api.unexpected_initial = true;
      auto r = load_verified_engine(evidence(), api); assert(!r.module && api.loads == 0); }
    { FakeLoader api; api.search = false;
      auto r = load_verified_engine(evidence(), api); assert(!r.module && api.loads == 0); }
    { FakeLoader api; api.bad_actual = true;
      auto r = load_verified_engine(evidence(), api);
      assert(!r.module && r.load_attempted && r.code_may_have_run && api.exports == 0); }
    { FakeLoader api; api.unexpected_after = true;
      auto r = load_verified_engine(evidence(), api);
      assert(!r.module && r.code_may_have_run && api.exports == 0); }
    { FakeLoader api; api.missing_export = true;
      auto r = load_verified_engine(evidence(), api);
      assert(!r.module && r.code_may_have_run && api.exports == 1); }
    { FakeLoader api; api.throws_load = true;
      auto r = load_verified_engine(evidence(), api);
      assert(!r.module && r.load_attempted && r.code_may_have_run); }
    for (int stage = 0; stage < 4; ++stage) {
        for (bool wrong : {false, true}) {
            FakeLoader api;
            if (wrong) api.wrong_mapping = stage;
            else api.unknown_mapping = stage;
            auto r = load_verified_engine(evidence(), api);
            assert(!r.module && !r.observations_match && api.exports == 0);
            assert(r.load_attempted == (stage >= 2));
            assert(r.code_may_have_run == (stage >= 2));
        }
    }
    { FakeLoader api; auto r = load_verified_engine(evidence(), api);
      // Caller-controlled observations and arbitrary export addresses are not a
      // native-callable capability, even when every synthetic check agrees.
      assert(!r.module && r.observations_match && r.load_attempted && r.code_may_have_run);
      assert(!r.execution_ready && arbitrary_factory_calls == 0);
      assert(api.loads == 1 && api.exports == 1); }
    std::cout << "portable loader checks passed\n";
}
