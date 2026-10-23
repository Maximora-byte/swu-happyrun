#include "issue110_filter_loader.hpp"
#include <algorithm>
#include <charconv>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace issue110_filter_probe::loader {
bool operator==(const FileBinding& a, const FileBinding& b) noexcept {
    return a.path == b.path && a.volume_serial == b.volume_serial &&
        a.file_id == b.file_id && a.sha256 == b.sha256;
}
namespace {
template<std::size_t N> bool present(const std::array<unsigned char, N>& value) {
    return std::any_of(value.begin(), value.end(), [](auto c) { return c != 0; });
}
bool absolute(const std::wstring& path) {
    if (path.size() < 4 || path.size() > 4096 || path[1] != L':' || path[2] != L'\\' ||
        !((path[0] >= L'A' && path[0] <= L'Z') || (path[0] >= L'a' && path[0] <= L'z')))
        return false;
    std::size_t start = 3;
    for (std::size_t i = 3; i <= path.size(); ++i) {
        if (i == path.size() || path[i] == L'\\') {
            const auto part = path.substr(start, i - start);
            if (part.empty() || part == L"." || part == L".." || part.back() == L'.' ||
                part.back() == L' ') return false;
            start = i + 1;
        } else if (path[i] < 0x20 || path[i] > 0x7e || path[i] == L'/' || path[i] == L':' ||
                   path[i] == L'"' || path[i] == L'<' || path[i] == L'>' || path[i] == L'|' ||
                   path[i] == L'*' || path[i] == L'?') return false;
    }
    return true;
}
bool valid_file(const FileBinding& value) {
    return absolute(value.path) && present(value.sha256) && present(value.file_id);
}
bool valid_set(const std::vector<FileBinding>& files) {
    if (files.empty() || files.size() > 64) return false;
    for (std::size_t i = 0; i < files.size(); ++i) {
        if (!valid_file(files[i])) return false;
        for (std::size_t j = 0; j < i; ++j)
            if (files[i].path == files[j].path || (files[i].volume_serial == files[j].volume_serial &&
                files[i].file_id == files[j].file_id)) return false;
    }
    return true;
}
bool matches(const ModuleObservation& actual, const FileBinding& expected) {
    return actual.loader_path == expected.path && actual.disk_file && actual.mapped_backing &&
        *actual.disk_file == expected && *actual.mapped_backing == expected;
}
bool same_set(const std::vector<ModuleObservation>& actual,
              const std::vector<FileBinding>& expected) {
    if (actual.size() != expected.size()) return false;
    std::vector<FileBinding> mapped;
    for (const auto& entry : actual) {
        const auto found = std::find_if(expected.begin(), expected.end(), [&](const auto& file) {
            return matches(entry, file);
        });
        if (found == expected.end()) return false;
        mapped.push_back(*found);
    }
    return valid_set(mapped);
}
#if defined(_WIN32)
bool same_evidence(const StageEvidence& a, const StageEvidence& b) {
    return a.request_validated == b.request_validated &&
        a.dependency_reviewed == b.dependency_reviewed && a.manifest_sha256 == b.manifest_sha256 &&
        a.stage_directory == b.stage_directory && a.files == b.files &&
        a.initial_modules == b.initial_modules && a.loaded_modules == b.loaded_modules;
}
#endif
bool valid(const StageEvidence& e) {
    constexpr const wchar_t* names[] = {L"issue110_filter_command_probe.exe", L"dbgeng.dll",
                                       L"dbghelp.dll"};
    if (!e.request_validated || !e.dependency_reviewed || !present(e.manifest_sha256) ||
        !absolute(e.stage_directory) || !valid_set(e.initial_modules) ||
        !valid_set(e.loaded_modules)) return false;
    const std::wstring suffix = L"\\issue110-filter-probe-1\\stage";
    if (e.stage_directory.size() <= suffix.size() ||
        e.stage_directory.substr(e.stage_directory.size() - suffix.size()) != suffix) return false;
    for (std::size_t i = 0; i < e.files.size(); ++i) {
        if (!valid_file(e.files[i]) || e.files[i].path != e.stage_directory + L"\\" + names[i])
            return false;
        if (std::find(e.loaded_modules.begin(), e.loaded_modules.end(), e.files[i]) ==
            e.loaded_modules.end()) return false;
    }
    return std::find(e.initial_modules.begin(), e.initial_modules.end(), e.files[0]) !=
               e.initial_modules.end() &&
        std::none_of(e.initial_modules.begin(), e.initial_modules.end(), [&](const auto& f) {
            return f == e.files[1] || f == e.files[2];
        });
}
}  // namespace
VerifiedEngineModule::VerifiedEngineModule(std::uintptr_t module, std::uintptr_t create) noexcept
    : owner_thread_(std::this_thread::get_id()), module_(module), create_(create) {}
VerifiedEngineModule::VerifiedEngineModule(VerifiedEngineModule&& source) noexcept
    : owner_thread_(source.owner_thread_), module_(std::exchange(source.module_, 0)),
      create_(std::exchange(source.create_, 0)), claimed_(source.claimed_) {}
bool VerifiedEngineModule::on_owner_thread() const noexcept {
    // Thread check precedes any access to mutable owner-only state.
    return std::this_thread::get_id() == owner_thread_ && module_ != 0 && create_ != 0;
}
#if defined(_WIN32)
decltype(&DebugCreate) VerifiedEngineModule::claim_debug_create() noexcept {
    if (!on_owner_thread() || claimed_) return nullptr;
    claimed_ = true;  // A failed DebugCreate is still an attempt, never retry it.
    return reinterpret_cast<decltype(&DebugCreate)>(create_);
}
#endif
LoadAttempt load_verified_engine(const StageEvidence& evidence, LoaderAPI& api) noexcept {
    LoadAttempt result;
    try {
        if (!valid(evidence) || !api.independently_reviewed(evidence) || !api.pin_stage(evidence) ||
            !matches(api.current_executable(), evidence.files[0]) || !api.revalidate_stage(evidence))
            return result;
        // No AddDllDirectory/Kits/PATH/current-directory or fallback search.
        if (!api.restrict_search(0x800)) return result;  // LOAD_LIBRARY_SEARCH_SYSTEM32
        result.actual_modules = api.modules();
        if (!same_set(result.actual_modules, evidence.initial_modules) ||
            !api.revalidate_stage(evidence)) return result;
        result.load_attempted = result.code_may_have_run = true;  // Set BEFORE calling loader.
        const auto module = api.load_absolute(evidence.files[1].path, 0x900);
        if (module == 0) return result;
        if (!matches(api.loaded_identity(module), evidence.files[1])) return result;
        result.actual_modules = api.modules();
        if (!same_set(result.actual_modules, evidence.loaded_modules) ||
            !api.revalidate_stage(evidence)) return result;
        const auto create = api.debug_create_export(module);
        if (create == 0) return result;
        result.observations_match = true;
#if defined(_WIN32)
        // RTTI identifies the final controlled implementation, not a caller-set
        // provenance flag. Its private seal consumes only its OWN native state.
        if (auto* native = dynamic_cast<WindowsLoaderAPI*>(&api)) result.module = native->seal();
#endif
    } catch (...) {
        // A post-load failure preserves code_may_have_run. Enumeration cannot
        // prevent DllMain and can miss transient modules or trusted dynamic loads.
    }
    return result;
}

namespace {
std::string hex_bytes(const unsigned char* bytes, std::size_t size) {
    std::string value;
    for (std::size_t i = 0; i < size; ++i) {
        value += "0123456789abcdef"[bytes[i] >> 4];
        value += "0123456789abcdef"[bytes[i] & 15];
    }
    return value;
}
std::string canonical_request(const StageEvidence& e, std::string_view nonce) {
    std::string value = R"({"schema":"swu.issue110.filter-request.v1","mode":"fixed_no_target","nonce":")";
    value += nonce;
    value += R"(","manifest_sha256":")" + hex_bytes(e.manifest_sha256.data(), 32);
    value += R"(","files":{)";
    constexpr const char* roles[] = {"exe", "dbgeng", "dbghelp"};
    for (std::size_t i = 0; i < e.files.size(); ++i) {
        if (i != 0) value += ',';
        value += std::string("\"") + roles[i] + R"(":{"volume_serial":)";
        std::array<char, 20> number{};
        const auto encoded = std::to_chars(number.data(), number.data() + number.size(),
                                           e.files[i].volume_serial);
        value.append(number.data(), encoded.ptr);
        value += R"(,"file_id_hex":")" + hex_bytes(e.files[i].file_id.data(), 16);
        value += R"(","sha256":")" + hex_bytes(e.files[i].sha256.data(), 32) + "\"}";
    }
    return value + "}}";
}
void retain_until_exit(std::shared_ptr<LoaderAPI> api) {
    // Deliberately process-lifetime, not static-destruction order: a trusted
    // engine may retain interfaces after our owned Release calls. No unload or
    // pin close is safe before OS teardown. No public runtime route calls this.
    static auto* held = new std::vector<std::shared_ptr<LoaderAPI>>;
    static auto* lock = new std::mutex;
    const std::lock_guard<std::mutex> guard(*lock);
    held->push_back(std::move(api));
}
}  // namespace
ClosedHostAttempt run_closed_host(std::string_view request, StageEvidence evidence,
    std::shared_ptr<LoaderAPI> api, std::uint32_t child_pid,
    issue110_filter_capsule::ByteSink& sink) noexcept {
    namespace c = issue110_filter_capsule;
    ClosedHostAttempt result;
    try {
#if defined(_WIN32)
        // A private request cannot assert the PID used to bind its receipt.
        if (child_pid != GetCurrentProcessId()) return result;
#endif
        // Strict canonical subset intentionally matches the sole private writer.
        // No JSON decoder, escapes, duplicate keys, dynamic data or coercions.
        constexpr std::string_view prefix =
            R"({"schema":"swu.issue110.filter-request.v1","mode":"fixed_no_target","nonce":")";
        if (!api || child_pid == 0 || request.size() > 16384 ||
            request.size() < prefix.size() + 32 || request.substr(0, prefix.size()) != prefix)
            return result;
        const auto nonce = request.substr(prefix.size(), 32);
        if (!std::all_of(nonce.begin(), nonce.end(), [](char ch) {
            return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
        }) || canonical_request(evidence, nonce) != request) return result;
        result.request_validated = true;
        evidence.request_validated = true;
        // Retain BEFORE dispatch: even a failing API may own unreturned pins.
        retain_until_exit(api);
        const auto load = load_verified_engine(evidence, *api);
        result.load_attempted = load.load_attempted;
        result.code_may_have_run = load.code_may_have_run;
        c::CapsuleInput capsule;
        capsule.nonce = nonce;
        capsule.child_pid = child_pid;
        capsule.stage = c::Stage::load_engine;
        capsule.issue = c::Issue::loader_blocked;
        // Lossless bounded WCHAR observations, never names as trust evidence.
        // No truncation: too many/long paths prevent a complete capsule.
        if (load.actual_modules.size() > capsule.module_paths_utf16le.size()) return result;
        std::array<std::string, 16> path_bytes;
        capsule.module_path_count = load.actual_modules.size();
        for (std::size_t i = 0; i < capsule.module_path_count; ++i) {
            const auto& path = load.actual_modules[i].loader_path;
            if (path.size() > c::kPathLimit / 2) return result;
            for (const auto ch : path) {
                const auto unit = static_cast<std::uint32_t>(ch);
                if (unit > 0xffff) return result;
                path_bytes[i] += static_cast<char>(unit & 0xff);
                path_bytes[i] += static_cast<char>(unit >> 8);
            }
            capsule.module_paths_utf16le[i] = path_bytes[i];
        }
#if defined(_WIN32)
        if (load.module) {
            CloseResult cleanup;
            const auto probe = windows_source_only::run_verified_probe(
                *load.module, result.engine_creation_attempted, cleanup);
            if (probe) {
                result.capsule = c::write_probe_capsule(*probe, nonce, child_pid,
                                                       result.engine_creation_attempted, sink,
                                                       capsule.module_paths_utf16le,
                                                       capsule.module_path_count);
                return result;
            }
            capsule.stage = c::Stage::create_engine;
            capsule.issue = c::Issue::engine_creation_failed;
            capsule.engine_creation_attempted = result.engine_creation_attempted;
            capsule.release = c::release_input(cleanup);
        }
#endif
        result.capsule = c::encode_capsule(capsule, sink);
    } catch (...) {
        // Never retry a loader, factory or partially written sink.
    }
    return result;
}
}  // namespace issue110_filter_probe::loader

#if defined(_WIN32)
#include <bcrypt.h>
#include <psapi.h>
// Official SDK declarations, linked only in a separately reviewed Windows build.
#pragma comment(lib, "bcrypt.lib")
namespace issue110_filter_probe::loader {
namespace {
constexpr DWORD kReadLimit = 64U * 1024U * 1024U;
void require(bool value) { if (!value) throw std::runtime_error("loader_observation_unknown"); }
struct FilePin {
    HANDLE value = INVALID_HANDLE_VALUE;
    std::wstring path;
    explicit FilePin(std::wstring name, bool directory = false) : path(std::move(name)) {
        value = CreateFileW(path.c_str(), directory ? FILE_READ_ATTRIBUTES : GENERIC_READ,
            FILE_SHARE_READ, nullptr, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | (directory ? FILE_FLAG_BACKUP_SEMANTICS : 0), nullptr);
        require(value != INVALID_HANDLE_VALUE);
    }
    FilePin(const FilePin&) = delete;
    ~FilePin() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); }
};
std::wstring final_path(HANDLE handle) {
    std::array<wchar_t, 8192> buffer{};
    const DWORD count = GetFinalPathNameByHandleW(handle, buffer.data(),
                                                static_cast<DWORD>(buffer.size()), 0);
    require(count > 4 && count < buffer.size());
    const std::wstring result(buffer.data(), count);
    require(result.substr(0, 4) == L"\\\\?\\");
    return result.substr(4);
}
FILE_ID_INFO identity(FilePin& pin, bool directory = false) {
    FILE_ATTRIBUTE_TAG_INFO attributes{};
    FILE_ID_INFO id{};
    require(GetFileInformationByHandleEx(pin.value, FileAttributeTagInfo, &attributes,
                                         sizeof(attributes)) != 0);
    require((attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) == 0 &&
        ((attributes.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) == directory);
    require(final_path(pin.value) == pin.path);
    require(GetFileInformationByHandleEx(pin.value, FileIdInfo, &id, sizeof(id)) != 0);
    return id;
}
struct Hash {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    ~Hash() {
        if (hash != nullptr) BCryptDestroyHash(hash);
        if (algorithm != nullptr) BCryptCloseAlgorithmProvider(algorithm, 0);
    }
};
FileBinding observe(FilePin& pin) {
    FileBinding result;
    result.path = pin.path;
    const auto id = identity(pin);
    result.volume_serial = id.VolumeSerialNumber;
    std::copy(std::begin(id.FileId.Identifier), std::end(id.FileId.Identifier), result.file_id.begin());
    LARGE_INTEGER length{}, zero{};
    require(GetFileSizeEx(pin.value, &length) != 0 && length.QuadPart >= 0 &&
            length.QuadPart <= kReadLimit);
    require(SetFilePointerEx(pin.value, zero, nullptr, FILE_BEGIN) != 0);
    Hash hash;
    require(BCryptOpenAlgorithmProvider(&hash.algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) == 0);
    require(BCryptCreateHash(hash.algorithm, &hash.hash, nullptr, 0, nullptr, 0, 0) == 0);
    std::array<unsigned char, 65536> bytes{};
    LONGLONG remaining = length.QuadPart;
    while (remaining > 0) {
        const auto count = static_cast<DWORD>((std::min)(remaining,
                                                       static_cast<LONGLONG>(bytes.size())));
        DWORD read = 0;
        require(ReadFile(pin.value, bytes.data(), count, &read, nullptr) != 0 && read == count);
        require(BCryptHashData(hash.hash, bytes.data(), read, 0) == 0);
        remaining -= read;
    }
    require(BCryptFinishHash(hash.hash, result.sha256.data(),
                            static_cast<ULONG>(result.sha256.size()), 0) == 0);
    const auto after = identity(pin);
    require(id.VolumeSerialNumber == after.VolumeSerialNumber &&
        std::equal(std::begin(id.FileId.Identifier), std::end(id.FileId.Identifier),
                   std::begin(after.FileId.Identifier)));
    return result;
}
std::wstring module_path(HMODULE module) {
    std::array<wchar_t, 8192> buffer{};
    const DWORD count = GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
    require(count > 0 && count < buffer.size());
    return std::wstring(buffer.data(), count);
}
}  // namespace
struct WindowsLoaderAPI::State {
    std::vector<std::unique_ptr<FilePin>> files;
    std::vector<std::pair<std::unique_ptr<FilePin>, FILE_ID_INFO>> directories;
    // No code currently populates admission: exact new-build/dependency AND
    // mapped-backing evidence are unknown. Public methods cannot supply it.
    std::optional<StageEvidence> admitted{};
    bool pinned = false;
    bool attempted = false;
    bool restricted = false;
    bool sealed = false;
    std::uintptr_t module = 0;
    std::uintptr_t create = 0;
};
WindowsLoaderAPI::WindowsLoaderAPI() : state_(new State) {}
WindowsLoaderAPI::~WindowsLoaderAPI() = default;
bool WindowsLoaderAPI::independently_reviewed(const StageEvidence&) {
    // Deliberately no approved manifest, EXE hash, dependency map or API-set /
    // SxS claim. The old 72e9aec EXE is NOT this build. Requires later review.
    return false;
}
bool WindowsLoaderAPI::pin_stage(const StageEvidence& e) {
    if (!state_->admitted || !same_evidence(e, *state_->admitted) ||
        !state_->files.empty() || !state_->directories.empty() || !valid(e)) return false;
    for (std::size_t pos = 3;;) {
        const auto end = e.stage_directory.find(L'\\', pos);
        const auto path = e.stage_directory.substr(0, end);
        auto pin = std::make_unique<FilePin>(path, true);
        const auto id = identity(*pin, true);
        state_->directories.emplace_back(std::move(pin), id);
        if (end == std::wstring::npos) break;
        pos = end + 1;
    }
    for (const auto& expected : e.loaded_modules) {
        auto pin = std::make_unique<FilePin>(expected.path);
        require(observe(*pin) == expected);
        state_->files.push_back(std::move(pin));
    }
    state_->pinned = revalidate_stage(e);
    return state_->pinned;
}
bool WindowsLoaderAPI::revalidate_stage(const StageEvidence& e) {
    if (!state_->admitted || !same_evidence(e, *state_->admitted) ||
        state_->files.size() != e.loaded_modules.size() || state_->directories.empty()) return false;
    for (auto& entry : state_->directories) {
        const auto id = identity(*entry.first, true);
        require(id.VolumeSerialNumber == entry.second.VolumeSerialNumber &&
            std::equal(std::begin(id.FileId.Identifier), std::end(id.FileId.Identifier),
                       std::begin(entry.second.FileId.Identifier)));
    }
    for (std::size_t i = 0; i < state_->files.size(); ++i)
        if (!(observe(*state_->files[i]) == e.loaded_modules[i])) return false;
    return true;
}
ModuleObservation WindowsLoaderAPI::current_executable() { return loaded_identity(0); }
bool WindowsLoaderAPI::restrict_search(std::uint32_t flags) {
    if (!state_->admitted || !state_->pinned || !revalidate_stage(*state_->admitted) ||
        flags != LOAD_LIBRARY_SEARCH_SYSTEM32 || state_->restricted) return false;
    const auto kernel = GetModuleHandleW(L"kernel32.dll");
    if (kernel == nullptr) return false;
    using SetDefaultPointer = decltype(&SetDefaultDllDirectories);
    const auto function = reinterpret_cast<SetDefaultPointer>(GetProcAddress(kernel,
                                                                           "SetDefaultDllDirectories"));
    if (function == nullptr || !function(LOAD_LIBRARY_SEARCH_SYSTEM32)) return false;
    state_->restricted = true;
    return true;
}
std::vector<ModuleObservation> WindowsLoaderAPI::modules() {
    std::array<HMODULE, 64> modules{};
    DWORD needed = 0;
    require(K32EnumProcessModules(GetCurrentProcess(), modules.data(), sizeof(modules), &needed) != 0);
    require(needed > 0 && needed <= sizeof(modules) && needed % sizeof(HMODULE) == 0);
    std::vector<ModuleObservation> result;
    for (std::size_t i = 0; i < needed / sizeof(HMODULE); ++i)
        result.push_back(loaded_identity(reinterpret_cast<std::uintptr_t>(modules[i])));
    return result;
}
std::uintptr_t WindowsLoaderAPI::load_absolute(const std::wstring& path, std::uint32_t flags) {
    if (!state_->admitted || !state_->pinned ||
        path != state_->admitted->files[1].path || !revalidate_stage(*state_->admitted) ||
        !state_->restricted || state_->attempted || !absolute(path) ||
        flags != (LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32)) return 0;
    state_->attempted = true;
    state_->module = reinterpret_cast<std::uintptr_t>(LoadLibraryExW(path.c_str(), nullptr, flags));
    return state_->module;
}
ModuleObservation WindowsLoaderAPI::loaded_identity(std::uintptr_t module) {
    ModuleObservation result;
    result.loader_path = module_path(reinterpret_cast<HMODULE>(module));
    FilePin pin(result.loader_path);
    result.disk_file = observe(pin);
    // mapped_backing remains unknown. GetModuleFileNameW plus a disk reopen/hash
    // does NOT associate this pin with the mapping (including KnownDLL/preloads).
    // Neither post-load enumeration nor a path-name API repairs that missing fact.
    return result;
}
std::uintptr_t WindowsLoaderAPI::debug_create_export(std::uintptr_t module) {
    if (!state_->admitted || !state_->pinned || !state_->attempted || module == 0 ||
        module != state_->module || state_->create != 0 ||
        !matches(loaded_identity(module), state_->admitted->files[1])) return 0;
    // Reject forwarded exports whose code address belongs to a different module.
    const auto owner = reinterpret_cast<HMODULE>(module);
    const auto address = GetProcAddress(owner, "DebugCreate");
    HMODULE actual = nullptr;
    if (address == nullptr || !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, reinterpret_cast<LPCWSTR>(address), &actual) ||
        actual != owner) return 0;
    state_->create = reinterpret_cast<std::uintptr_t>(address);
    return state_->create;
}
std::unique_ptr<VerifiedEngineModule> WindowsLoaderAPI::seal() {
    if (!state_->admitted || !state_->pinned || !state_->restricted || !state_->attempted ||
        state_->sealed || state_->module == 0 || state_->create == 0 ||
        !revalidate_stage(*state_->admitted) ||
        !matches(loaded_identity(state_->module), state_->admitted->files[1]) ||
        !same_set(modules(), state_->admitted->loaded_modules)) return {};
    state_->sealed = true;
    return std::unique_ptr<VerifiedEngineModule>(
        new VerifiedEngineModule(state_->module, state_->create));
}
}  // namespace issue110_filter_probe::loader
#endif
