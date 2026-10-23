#ifndef SWU_ISSUE110_FILTER_LOADER_HPP
#define SWU_ISSUE110_FILTER_LOADER_HPP

// Internal, non-entry loader boundary. A synthetic LoaderAPI is not production
// admission. Windows admission remains closed until an exact new build and its
// dependencies have independently reviewed evidence. No command/main uses this.
#include "issue110_filter_capsule.hpp"
#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <DbgEng.h>
#endif

namespace issue110_filter_probe::loader { class VerifiedEngineModule; }
#if defined(_WIN32)
namespace issue110_filter_probe::windows_source_only {
struct FactoryAttempt;
FactoryAttempt make_verified_source_adapter(loader::VerifiedEngineModule&) noexcept;
std::optional<Result> run_verified_probe(loader::VerifiedEngineModule&, bool&, CloseResult&) noexcept;
}
#endif

namespace issue110_filter_probe::loader {
// A binding observed on a held disk file, not a claim about mapped bytes.
struct FileBinding {
    std::wstring path{};
    std::uint64_t volume_serial = 0;
    std::array<unsigned char, 16> file_id{};
    std::array<unsigned char, 32> sha256{};
};
bool operator==(const FileBinding&, const FileBinding&) noexcept;
struct ModuleObservation {
    std::wstring loader_path{};  // A loader name alone proves no backing identity.
    std::optional<FileBinding> disk_file{};
    // Must come from independently established association of this actual mapping
    // to the retained file, NEVER from opening loader_path. Native evidence absent.
    std::optional<FileBinding> mapped_backing{};
};
struct StageEvidence {
    // Populated only from a validated private request and independent dependency
    // review. Path strings are derived from the held current EXE, not the request.
    // These fields alone cannot approve a production build.
    bool request_validated = false;
    bool dependency_reviewed = false;
    std::array<unsigned char, 32> manifest_sha256{};
    std::wstring stage_directory{};
    std::array<FileBinding, 3> files{};  // EXE, dbgeng, dbghelp, in that order.
    std::vector<FileBinding> initial_modules{};
    std::vector<FileBinding> loaded_modules{};
};
class LoaderAPI {
public:
    virtual ~LoaderAPI() = default;
    virtual bool independently_reviewed(const StageEvidence&) = 0;
    // Retain non-inherited read-only/no-WRITE-or-DELETE-sharing pins until the
    // host exits. API and pins must outlive all its returned module owners.
    virtual bool pin_stage(const StageEvidence&) = 0;
    virtual bool revalidate_stage(const StageEvidence&) = 0;
    virtual ModuleObservation current_executable() = 0;
    virtual bool restrict_search(std::uint32_t flags) = 0;
    virtual std::vector<ModuleObservation> modules() = 0;
    virtual std::uintptr_t load_absolute(const std::wstring&, std::uint32_t flags) = 0;
    virtual ModuleObservation loaded_identity(std::uintptr_t) = 0;
    virtual std::uintptr_t debug_create_export(std::uintptr_t) = 0;
    // Deliberately NO unload operation. A failed load may have run DllMain, and
    // release counts never prove global engine disposal. Keep mappings to exit.
};
struct LoadAttempt;
LoadAttempt load_verified_engine(const StageEvidence&, LoaderAPI&) noexcept;
class VerifiedEngineModule final {
public:
    VerifiedEngineModule(const VerifiedEngineModule&) = delete;
    VerifiedEngineModule& operator=(const VerifiedEngineModule&) = delete;
    VerifiedEngineModule(VerifiedEngineModule&&) noexcept;
    VerifiedEngineModule& operator=(VerifiedEngineModule&&) = delete;
    ~VerifiedEngineModule() = default;  // Intentionally does not unload the DLL.
    bool on_owner_thread() const noexcept;
private:
    // A caller-controlled LoaderAPI can never mint this callable capability.
    // Only the final, independently gated native implementation is a friend.
#if defined(_WIN32)
    friend class WindowsLoaderAPI;
#endif
    VerifiedEngineModule(std::uintptr_t module, std::uintptr_t create) noexcept;
#if defined(_WIN32)
    friend windows_source_only::FactoryAttempt
        windows_source_only::make_verified_source_adapter(VerifiedEngineModule&) noexcept;
    decltype(&DebugCreate) claim_debug_create() noexcept;
#endif
    const std::thread::id owner_thread_;
    std::uintptr_t module_ = 0;
    std::uintptr_t create_ = 0;
    bool claimed_ = false;
};
struct LoadAttempt {
    std::unique_ptr<VerifiedEngineModule> module{};
    // Portable/fake result only; not convertible to a native capability and never
    // stores an export address. Matching observations are NOT production admission.
    bool observations_match = false;
    bool load_attempted = false;
    bool code_may_have_run = false;
    bool execution_ready = false;
    // Observations, not a DllMain-before-execution policy or complete sandbox.
    std::vector<ModuleObservation> actual_modules{};
};
// Internal canonical request from _request, never main/arguments/environment.
// Parsing binds only identities/digests, not path/commands or build admission.
// Valid calls retain the owning API and all pins until process exit, including
// post-load failures; returning a receipt cannot release backing file ownership.
struct ClosedHostAttempt {
    bool request_validated = false;
    bool load_attempted = false;
    bool code_may_have_run = false;
    bool engine_creation_attempted = false;
    issue110_filter_capsule::EncodeResult capsule{};
};
ClosedHostAttempt run_closed_host(std::string_view request, StageEvidence evidence,
    std::shared_ptr<LoaderAPI> api, std::uint32_t child_pid,
    issue110_filter_capsule::ByteSink& sink) noexcept;

#if defined(_WIN32)
// Official SDK implementation; no calls on construction and no exported entry.
// New EXE/dependency evidence is absent, so independently_reviewed returns false.
class WindowsLoaderAPI final : public LoaderAPI {
public:
    WindowsLoaderAPI();
    ~WindowsLoaderAPI() override;
    bool independently_reviewed(const StageEvidence&) override;
    bool pin_stage(const StageEvidence&) override;
    bool revalidate_stage(const StageEvidence&) override;
    ModuleObservation current_executable() override;
    bool restrict_search(std::uint32_t) override;
    std::vector<ModuleObservation> modules() override;
    std::uintptr_t load_absolute(const std::wstring&, std::uint32_t) override;
    ModuleObservation loaded_identity(std::uintptr_t) override;
    std::uintptr_t debug_create_export(std::uintptr_t) override;
private:
    friend LoadAttempt load_verified_engine(const StageEvidence&, LoaderAPI&) noexcept;
    std::unique_ptr<VerifiedEngineModule> seal();
    struct State;
    std::unique_ptr<State> state_;
};
#endif
}  // namespace issue110_filter_probe::loader
#endif
