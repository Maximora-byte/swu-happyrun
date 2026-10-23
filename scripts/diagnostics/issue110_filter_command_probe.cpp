// Source-only Issue 110 adapter. This file is NOT a runnable native probe.
// main stays blocked on every platform. The Windows branch has NOT been built
// or executed here; a downloaded reference header is not an installed SDK.
// Declaration reference: microsoft/win32metadata at
// 71033001b4479c6566546b68d32276e70a8d68b9, SDK 10.0.26100.6584,
// DbgEng.h SHA256 a9037bf9a096700082ec5d4d96a98d1d98dee6c8ed71b3eac8de64c1fd9a0f4f.
#include <cstdio>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
// Instantiate the SDK's official IID definitions, not copied GUIDs or vtables.
#include <initguid.h>
#include <DbgEng.h>

#include "issue110_filter_probe_core.hpp"
#include "issue110_filter_loader.hpp"
#include <atomic>
#include <limits>
#include <memory>
#include <new>

namespace issue110_filter_probe::windows_source_only {
using DebugCreatePointer = decltype(&DebugCreate);
static_assert(sizeof(HRESULT) == sizeof(HResult));
static_assert(kGetterCapacity <= (std::numeric_limits<ULONG>::max)());
static_assert(kMaxFilters <= (std::numeric_limits<ULONG>::max)());

static HResult observed(HRESULT value) noexcept {
    return static_cast<HResult>(value);
}

struct ParameterObservation {
    std::uint32_t index = 0;
    HResult hr = 1;
};
struct NativeObservations {
    std::optional<HResult> create_hresult{};
    std::optional<HResult> control_query_hresult{};
    std::optional<TargetReply> startup_target{};
    std::optional<HResult> callback_registration_hresult{};
    std::optional<HResult> filter_count_hresult{};
    std::uint32_t specific_events = 0;
    std::uint32_t specific_exceptions = 0;
    std::uint32_t arbitrary_exceptions = 0;
    std::array<ParameterObservation, kMaxFilters> parameters{};
    std::size_t parameter_calls = 0;
};

// The callback owns its capture state. It never refers back to an engine or a
// temporary reply, and never makes engine calls. A retained engine reference
// keeps this object alive even if detaching its registration fails.
class OutputCollector final : public IDebugOutputCallbacks {
public:
    explicit OutputCollector(DWORD owner_thread) noexcept : owner_thread_(owner_thread) {}

    STDMETHODIMP QueryInterface(REFIID iid, PVOID* result) noexcept override {
        if (result == nullptr) return E_POINTER;
        *result = nullptr;
        if (!on_owner_thread()) return RPC_E_WRONG_THREAD;
        if (IsEqualIID(iid, IID_IUnknown) || IsEqualIID(iid, IID_IDebugOutputCallbacks)) {
            *result = static_cast<IDebugOutputCallbacks*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() noexcept override {
        on_owner_thread();
        return references_.fetch_add(1, std::memory_order_relaxed) + 1;
    }
    STDMETHODIMP_(ULONG) Release() noexcept override {
        on_owner_thread();
        const ULONG remaining = references_.fetch_sub(1, std::memory_order_acq_rel) - 1;
        if (remaining == 0) delete this;
        return remaining;
    }
    STDMETHODIMP Output(ULONG, PCSTR text) noexcept override {
        // DbgEng ignores this HRESULT, so the atomic error flag is also checked.
        // A wrong-thread callback touches no non-atomic capture state.
        if (!on_owner_thread()) return RPC_E_WRONG_THREAD;
        if (phase_ == Phase::sealed) {
            invalid_phase_ = true;
            return E_UNEXPECTED;
        }
        if (phase_ == Phase::idle) return S_OK;
        if (text == nullptr) {
            invalid_text_ = true;
            return E_POINTER;
        }
        std::size_t length = 0;
        // Read no more than the fixed capacity. A missing terminator within the
        // bound is rejected, not resized, retried, or scanned without a limit.
        while (length < kOutputCapacity && text[length] != '\0') ++length;
        if (length == kOutputCapacity) {
            invalid_text_ = true;
            return E_INVALIDARG;
        }
        output_.append(OutputPhase::sx, text, length);
        return S_OK;
    }
    void begin_sx() noexcept {
        if (!on_owner_thread()) return;
        if (phase_ != Phase::idle) invalid_phase_ = true;
        phase_ = Phase::capturing;
        output_.begin();
    }
    void seal_sx() noexcept {
        if (!on_owner_thread()) return;
        if (phase_ != Phase::capturing) invalid_phase_ = true;
        output_.finish();
        phase_ = Phase::sealed;
    }
    BoundedOutput snapshot() const noexcept { return output_; }
    bool wrong_thread() const noexcept { return wrong_thread_.load(std::memory_order_relaxed); }
    bool invalid_text() const noexcept { return invalid_text_ || invalid_phase_; }
    bool violation() const noexcept { return wrong_thread() || invalid_text(); }

private:
    enum class Phase { idle, capturing, sealed };
    ~OutputCollector() = default;
    bool on_owner_thread() noexcept {
        if (GetCurrentThreadId() == owner_thread_) return true;
        wrong_thread_.store(true, std::memory_order_relaxed);
        return false;
    }
    const DWORD owner_thread_;
    std::atomic<ULONG> references_{1};
    std::atomic<bool> wrong_thread_{false};
    Phase phase_ = Phase::idle;
    bool invalid_text_ = false;
    bool invalid_phase_ = false;
    BoundedOutput output_{};
};

class NativeEngine;
struct FactoryAttempt;
FactoryAttempt make_verified_source_adapter(loader::VerifiedEngineModule& module) noexcept;

class NativeEngine final : public Engine {
public:
    ~NativeEngine() override { close(); }

    TargetReply no_target() override {
        if (!can_query_target()) return {observed(E_UNEXPECTED), TargetState::unknown};
        ULONG target_class = (std::numeric_limits<ULONG>::max)();
        ULONG qualifier = (std::numeric_limits<ULONG>::max)();
        const HRESULT hr = control_->GetDebuggeeType(&target_class, &qualifier);
        TargetState state = TargetState::unknown;
        if (hr == S_OK) {
            if (target_class == DEBUG_CLASS_UNINITIALIZED && qualifier == 0) {
                state = TargetState::no_target;
            } else if (target_class == DEBUG_CLASS_KERNEL || target_class == DEBUG_CLASS_USER_WINDOWS) {
                state = TargetState::target;
            }
        }
        target_gate_ = hr == S_OK && state == TargetState::no_target;
        if (!target_gate_) blocked_ = true;
        return {observed(hr), state};
    }

    FilterReply enumerate_filters() override {
        FilterReply reply;
        if (!consume_step(Step::enumerate, Step::registration)) return reply;
        const ULONG unknown = (std::numeric_limits<ULONG>::max)();
        ULONG events = unknown, specific = unknown, arbitrary = unknown;
        HRESULT hr = control_->GetNumberEventFilters(&events, &specific, &arbitrary);
        observations_.filter_count_hresult = observed(hr);
        observations_.specific_events = events;
        observations_.specific_exceptions = specific;
        observations_.arbitrary_exceptions = arbitrary;
        reply.hr = observed(hr);
        if (hr != S_OK) { blocked_ = true; return reply; }
        const std::uint64_t total = static_cast<std::uint64_t>(events) + specific + arbitrary;
        if (total == 0 || total > kMaxFilters) {
            // Preserve raw counts separately and expose an invalid bounded count.
            reply.total_filter_count = total == 0 ? 0 : static_cast<std::uint32_t>(kMaxFilters + 1);
            blocked_ = true;
            return reply;
        }
        reply.total_filter_count = static_cast<std::uint32_t>(total);
        for (ULONG index = events; index < total; ++index) {
            DEBUG_EXCEPTION_FILTER_PARAMETERS parameters{};
            // Codes=nullptr means Start is an actual combined filter-table index.
            hr = control_->GetExceptionFilterParameters(1, nullptr, index, &parameters);
            observations_.parameters[observations_.parameter_calls++] = {index, observed(hr)};
            reply.hr = observed(hr);
            if (hr != S_OK) { blocked_ = true; return reply; }
            reply.records[reply.count++] = {parameters.ExceptionCode, index};
        }
        return reply;
    }

    RegistrationReply register_fixed_command() override {
        RegistrationReply reply;
        if (!consume_step(Step::registration, Step::getter_a)) return reply;
        reply.execute_called = true;
        reply.hr = observed(control_->Execute(DEBUG_OUTCTL_THIS_CLIENT, kRegistrationCommand,
            DEBUG_EXECUTE_NOT_LOGGED | DEBUG_EXECUTE_NO_REPEAT));
        // Drain registration output while capture remains idle, even if Execute
        // failed. This is a flush, never a command retry or a fallback setter.
        reply.flush_hresult = observed(client_->FlushCallbacks());
        reply.callback_wrong_thread = callback_->wrong_thread();
        reply.callback_invalid_text = callback_->invalid_text();
        if (reply.hr != 0 || *reply.flush_hresult != 0 || callback_->violation()) blocked_ = true;
        return reply;
    }

    GetterReply get_fixed_command(std::uint32_t index) override {
        GetterReply reply;
        reply.bytes.fill(0xa5);
        const Step next = step_ == Step::getter_a ? Step::display : Step::complete;
        if ((step_ != Step::getter_a && step_ != Step::getter_b) ||
            !consume_step(step_, next)) return reply;
        // Core resolves the unique AV from the enumerated records. No fixed index
        // or code-to-index assumption is accepted by this adapter.
        bool found = false;
        for (std::size_t i = 0; i < observations_.parameter_calls; ++i) {
            if (observations_.parameters[i].index == index) found = true;
        }
        if (!found || (selected_index_ && *selected_index_ != index)) {
            blocked_ = true;
            return reply;
        }
        selected_index_ = index;
        ULONG command_size = 0;
        reply.hr = observed(control_->GetExceptionFilterSecondCommand(index,
            reinterpret_cast<PSTR>(reply.bytes.data()), static_cast<ULONG>(reply.bytes.size()),
            &command_size));
        reply.reported_length = command_size;
        if (reply.hr != 0) blocked_ = true;
        return reply;
    }

    DisplayReply display_fixed_sx() override {
        DisplayReply reply;
        if (!consume_step(Step::display, Step::getter_b)) return reply;
        // Pre-flush outside capture; post-flush before sealing the sx phase.
        // The default client output mask and native output completeness have NOT
        // been verified. Empty output is rejected by core, and even nonempty
        // output remains format_unknown, never a full native display claim.
        reply.pre_flush_hresult = observed(client_->FlushCallbacks());
        if (*reply.pre_flush_hresult != 0 || callback_->violation()) {
            reply.callback_wrong_thread = callback_->wrong_thread();
            reply.callback_invalid_text = callback_->invalid_text();
            blocked_ = true;
            return reply;
        }
        callback_->begin_sx();
        reply.execute_called = true;
        reply.hr = observed(control_->Execute(DEBUG_OUTCTL_THIS_CLIENT, "sx",
            DEBUG_EXECUTE_NOT_LOGGED | DEBUG_EXECUTE_NO_REPEAT));
        reply.post_flush_hresult = observed(client_->FlushCallbacks());
        callback_->seal_sx();
        reply.output = callback_->snapshot();
        reply.callback_wrong_thread = callback_->wrong_thread();
        reply.callback_invalid_text = callback_->invalid_text();
        if (reply.hr != 0 || *reply.post_flush_hresult != 0 || callback_->violation()) blocked_ = true;
        return reply;
    }

    CloseResult close() noexcept override {
        if (GetCurrentThreadId() != owner_thread_) {
            // Reject before touching owner-only state or engine interfaces.
            wrong_thread_.store(true, std::memory_order_relaxed);
            CloseResult rejected;
            rejected.wrong_thread = true;
            return rejected;
        }
        if (closed_) return cleanup_;
        closed_ = true;
        cleanup_.wrong_thread = wrong_thread_.load(std::memory_order_relaxed);
        if (callback_ != nullptr) cleanup_.callback_violation = callback_->violation();
        if (client_ != nullptr && callback_registration_attempted_) {
            cleanup_.detach_hresult = observed(client_->SetOutputCallbacks(nullptr));
        }
        if (control_ != nullptr) {
            IDebugControl* owned = control_;
            control_ = nullptr;
            cleanup_.control_release_return = owned->Release();
        }
        if (client_ != nullptr) {
            IDebugClient* owned = client_;
            client_ = nullptr;
            cleanup_.client_release_return = owned->Release();
        }
        if (callback_ != nullptr) {
            // We retain our initial callback reference until after releasing the
            // interfaces. Failed detach cannot cause a dangling borrowed buffer.
            cleanup_.callback_violation = cleanup_.callback_violation || callback_->violation();
            OutputCollector* owned = callback_;
            callback_ = nullptr;
            cleanup_.callback_release_return = owned->Release();
        }
        cleanup_.all_owned_release_calls_issued = true;
        // A Release count is only an observation. Never infer global disposal,
        // and never unload an externally owned module.
        cleanup_.engine_disposal_confirmed = false;
        return cleanup_;
    }
    const NativeObservations& observations() const noexcept { return observations_; }

private:
    friend FactoryAttempt make_verified_source_adapter(loader::VerifiedEngineModule&) noexcept;
    enum class Step { enumerate, registration, getter_a, display, getter_b, complete };
    NativeEngine() noexcept : owner_thread_(GetCurrentThreadId()) {}
    bool can_query_target() noexcept {
        if (GetCurrentThreadId() != owner_thread_) {
            wrong_thread_.store(true, std::memory_order_relaxed);
            return false;
        }
        // A previous stage error must not hide its required read-only post-query.
        // This grants no permission for another registration/getter/display stage.
        return !closed_ && control_ != nullptr;
    }
    bool usable() noexcept {
        if (GetCurrentThreadId() != owner_thread_) {
            wrong_thread_.store(true, std::memory_order_relaxed);
            return false;
        }
        if (wrong_thread_.load(std::memory_order_relaxed) || closed_ || blocked_ ||
            control_ == nullptr || client_ == nullptr || callback_ == nullptr ||
            callback_->violation()) return false;
        return true;
    }
    bool consume_step(Step expected, Step next) noexcept {
        if (!usable() || !target_gate_ || step_ != expected) return false;
        target_gate_ = false;
        step_ = next;
        return true;
    }
    const DWORD owner_thread_;
    std::atomic<bool> wrong_thread_{false};
    IDebugClient* client_ = nullptr;
    IDebugControl* control_ = nullptr;
    OutputCollector* callback_ = nullptr;
    bool callback_registration_attempted_ = false;
    bool closed_ = false;
    bool blocked_ = false;
    bool target_gate_ = false;
    Step step_ = Step::enumerate;
    std::optional<std::uint32_t> selected_index_{};
    NativeObservations observations_{};
    CloseResult cleanup_{};
};

struct FactoryAttempt {
    std::unique_ptr<NativeEngine> engine{};
    NativeObservations observations{};
    CloseResult cleanup{};
    bool execution_ready = false;
    bool engine_creation_attempted = false;
};

// UNVERIFIED Windows ABI/runtime remains blocked. Only the move-only loader
// owner can issue its single factory claim; a raw caller-supplied function pointer
// is no longer accepted. Module mapping is intentionally retained until exit,
// including factory failure and interface cleanup with unconfirmed disposal.
FactoryAttempt make_verified_source_adapter(loader::VerifiedEngineModule& module) noexcept {
    FactoryAttempt result;
    const DebugCreatePointer verified_debug_create = module.claim_debug_create();
    if (verified_debug_create == nullptr) return result;
    std::unique_ptr<NativeEngine> engine(new (std::nothrow) NativeEngine());
    if (!engine) return result;
    engine->callback_ = new (std::nothrow) OutputCollector(engine->owner_thread_);
    if (engine->callback_ == nullptr) {
        result.cleanup = engine->close();
        return result;
    }
    const auto fail = [&]() noexcept {
        result.observations = engine->observations_;
        result.cleanup = engine->close();
    };
    PVOID created = nullptr;
    result.engine_creation_attempted = true;
    const HRESULT create_hr = verified_debug_create(IID_IDebugClient, &created);
    engine->client_ = static_cast<IDebugClient*>(created);
    engine->observations_.create_hresult = observed(create_hr);
    if (create_hr != S_OK || engine->client_ == nullptr) { fail(); return result; }
    PVOID queried = nullptr;
    const HRESULT query_hr = engine->client_->QueryInterface(IID_IDebugControl, &queried);
    engine->control_ = static_cast<IDebugControl*>(queried);
    engine->observations_.control_query_hresult = observed(query_hr);
    if (query_hr != S_OK || engine->control_ == nullptr) { fail(); return result; }
    // A fresh client is not enough to assert no target; query it before even
    // registering this output-only callback. Unsupported no-target APIs block.
    engine->observations_.startup_target = engine->no_target();
    if (engine->observations_.startup_target->hr != 0 ||
        engine->observations_.startup_target->state != TargetState::no_target) {
        fail(); return result;
    }
    engine->callback_registration_attempted_ = true;
    const HRESULT callback_hr = engine->client_->SetOutputCallbacks(engine->callback_);
    engine->observations_.callback_registration_hresult = observed(callback_hr);
    if (callback_hr != S_OK || engine->callback_->violation()) { fail(); return result; }
    // Core must perform its own initial no-target gate, not reuse startup state.
    engine->target_gate_ = false;
    result.observations = engine->observations_;
    result.engine = std::move(engine);
    return result;
}
// Internal-only bridge. The module capability cannot come from an arbitrary
// function pointer or fake API, and its API/pins are retained by run_closed_host.
std::optional<Result> run_verified_probe(loader::VerifiedEngineModule& module,
                                        bool& attempted, CloseResult& cleanup) noexcept {
    auto factory = make_verified_source_adapter(module);
    attempted = factory.engine_creation_attempted;
    cleanup = factory.cleanup;
    if (!factory.engine) return std::nullopt;
    return run_probe(*factory.engine);
}
}  // namespace issue110_filter_probe::windows_source_only
#endif

int main() {
    std::fputs("{\"status\":\"blocked\",\"execution_ready\":false,\"passed\":false,"
               "\"native_execution_attempted\":false,"
               "\"reason\":\"source_only_unverified_windows_integration\"}\n", stdout);
    return 2;
}
