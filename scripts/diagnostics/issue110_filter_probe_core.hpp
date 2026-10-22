#ifndef SWU_ISSUE110_FILTER_PROBE_CORE_HPP
#define SWU_ISSUE110_FILTER_PROBE_CORE_HPP

// Portable software-only orchestration. This interface does not accept arbitrary
// commands, start a target, open the synthetic path, or establish a time limit.
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace issue110_filter_probe {
using HResult = std::int32_t;
inline constexpr char kIntendedCommand[] = "$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb";
inline constexpr char kRegistrationCommand[] =
    "sxd -c2 \"$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb\" av";
inline constexpr std::uint32_t kAccessViolationCode = 0xc0000005u;
inline constexpr std::size_t kGetterCapacity = 4096;
inline constexpr std::size_t kMaxFilters = 256;
inline constexpr std::size_t kOutputCapacity = 65536;

enum class TargetState { unknown, no_target, target };
enum class OutputPhase { other, sx };
enum class Stage {
    not_started, target_before_enumeration, enumerate_filters,
    target_after_enumeration, register_command, register_flush, target_after_registration,
    getter_a, target_after_getter_a, display_pre_flush, display_sx, display_post_flush,
    target_after_display,
    getter_b, target_after_getter_b, close, observations_complete
};
enum class Issue {
    none, call_not_s_ok, call_not_observed, callback_violation, target_not_absent, filter_count_invalid,
    filter_index_invalid, filter_indices_duplicate, av_missing, av_duplicate,
    getter_length_invalid, getter_terminator_missing, getter_embedded_nul,
    getter_non_ascii, getter_changed, output_incomplete, output_ambiguous, output_overflow,
    output_non_ascii, cleanup_incomplete, adapter_exception
};
enum class Comparison { not_observed, equal, different };
enum class DisplayComparison { format_unknown };

struct TargetReply { HResult hr = 1; TargetState state = TargetState::unknown; };
struct FilterRecord { std::uint32_t code = 0; std::uint32_t index = 0; };
struct FilterReply {
    HResult hr = 1;
    std::uint32_t total_filter_count = 0;
    std::uint32_t count = 0;
    std::array<FilterRecord, kMaxFilters> records{};
};
struct GetterReply {
    HResult hr = 1;
    std::uint32_t reported_length = 0;
    std::array<unsigned char, kGetterCapacity> bytes{};
};

class BoundedOutput {
public:
    void begin() noexcept {
        if (begun_ || finished_) ambiguous_ = true;
        begun_ = true;
    }
    void append(OutputPhase phase, const char* bytes, std::size_t length) noexcept {
        if (!begun_ || finished_ || phase != OutputPhase::sx ||
            (bytes == nullptr && length != 0)) {
            ambiguous_ = true;
            return;
        }
        if (length > kOutputCapacity - size_) {
            overflow_ = true;
            return;
        }
        for (std::size_t i = 0; i < length; ++i) {
            const auto byte = static_cast<unsigned char>(bytes[i]);
            if (!((byte >= 0x20 && byte <= 0x7e) || byte == '\t' ||
                  byte == '\r' || byte == '\n')) non_ascii_ = true;
            bytes_[size_++] = bytes[i];
        }
    }
    void finish() noexcept {
        if (!begun_ || finished_) ambiguous_ = true;
        finished_ = true;
    }
    std::size_t size() const noexcept { return size_; }
    const char* data() const noexcept { return bytes_.data(); }
    Issue issue() const noexcept {
        if (overflow_) return Issue::output_overflow;
        if (ambiguous_) return Issue::output_ambiguous;
        if (!begun_ || !finished_ || size_ == 0) return Issue::output_incomplete;
        if (non_ascii_) return Issue::output_non_ascii;
        return Issue::none;
    }
private:
    std::array<char, kOutputCapacity> bytes_{};
    std::size_t size_ = 0;
    bool begun_ = false;
    bool finished_ = false;
    bool ambiguous_ = false;
    bool overflow_ = false;
    bool non_ascii_ = false;
};
struct RegistrationReply {
    HResult hr = 1;
    bool execute_called = false;
    std::optional<HResult> flush_hresult{};
    bool callback_wrong_thread = false;
    bool callback_invalid_text = false;
};
struct DisplayReply {
    HResult hr = 1;
    bool execute_called = false;
    std::optional<HResult> pre_flush_hresult{};
    std::optional<HResult> post_flush_hresult{};
    bool callback_wrong_thread = false;
    bool callback_invalid_text = false;
    BoundedOutput output{};
};
struct CloseResult {
    bool all_owned_release_calls_issued = false;
    bool engine_disposal_confirmed = false;
    std::optional<HResult> detach_hresult{};
    std::optional<std::uint32_t> control_release_return{};
    std::optional<std::uint32_t> client_release_return{};
    std::optional<std::uint32_t> callback_release_return{};
    bool wrong_thread = false;
    bool callback_violation = false;
};

// The adapter must use documented APIs on one thread and retain exact HRESULTs.
// register_fixed_command registers kRegistrationCommand, never executes its
// payload. get_fixed_command always queries the second-chance command.
// close detaches callbacks and releases only owned references. A Release return
// value does not establish whether the engine as a whole has been destroyed.
class Engine {
public:
    virtual ~Engine() = default;
    virtual TargetReply no_target() = 0;
    virtual FilterReply enumerate_filters() = 0;
    virtual RegistrationReply register_fixed_command() = 0;
    virtual GetterReply get_fixed_command(std::uint32_t filter_index) = 0;
    virtual DisplayReply display_fixed_sx() = 0;
    virtual CloseResult close() noexcept = 0;
};
struct CallObservation { Stage stage = Stage::not_started; HResult hr = 1; };
struct Result {
    Stage stage = Stage::not_started;
    Issue issue = Issue::none;
    bool observations_complete = false;
    bool execution_ready = false;
    bool passed = false;
    DisplayComparison display_comparison = DisplayComparison::format_unknown;
    Comparison a_expected = Comparison::not_observed;
    Comparison b_expected = Comparison::not_observed;
    Comparison ab_stability = Comparison::not_observed;
    bool getter_a_valid = false;
    bool getter_b_valid = false;
    GetterReply getter_a{};
    GetterReply getter_b{};
    BoundedOutput output{};
    std::array<CallObservation, 14> trace{};
    std::size_t trace_count = 0;
    CloseResult cleanup{};
};

namespace detail {
inline Issue validate_getter(const GetterReply& reply) noexcept {
    if (reply.reported_length == 0 || reply.reported_length > kGetterCapacity)
        return Issue::getter_length_invalid;
    if (reply.bytes[reply.reported_length - 1] != 0)
        return Issue::getter_terminator_missing;
    for (std::size_t i = 0; i + 1 < reply.reported_length; ++i) {
        if (reply.bytes[i] == 0) return Issue::getter_embedded_nul;
        if (reply.bytes[i] < 0x20 || reply.bytes[i] > 0x7e)
            return Issue::getter_non_ascii;
    }
    return Issue::none;
}
inline Comparison expected(const GetterReply& reply) noexcept {
    return reply.reported_length == sizeof(kIntendedCommand) &&
        std::equal(reply.bytes.begin(), reply.bytes.begin() + reply.reported_length,
                   kIntendedCommand) ? Comparison::equal : Comparison::different;
}
}  // namespace detail

// There is deliberately no retry, target lifecycle operation, file operation,
// timeout guarantee, sx parser, or product-success transition in this function.
inline Result run_probe(Engine& engine) {
    Result result;
    Stage current_stage = Stage::not_started;
    const auto block = [&](Stage stage, Issue issue) {
        if (issue != Issue::none && result.issue == Issue::none) {
            result.stage = stage;
            result.issue = issue;
        }
    };
    const auto record = [&](Stage stage, HResult hr) {
        result.trace[result.trace_count++] = {stage, hr};
        if (hr != 0) block(stage, Issue::call_not_s_ok);
    };
    const auto record_optional = [&](Stage stage, std::optional<HResult> hr) {
        if (hr) record(stage, *hr);
        else block(stage, Issue::call_not_observed);
    };
    const auto target_gate = [&](Stage stage) {
        current_stage = stage;
        const auto target = engine.no_target();
        record(stage, target.hr);
        if (target.hr == 0 && target.state != TargetState::no_target)
            block(stage, Issue::target_not_absent);
    };
    try {
        do {
            target_gate(Stage::target_before_enumeration);
            if (result.issue != Issue::none) break;
            current_stage = Stage::enumerate_filters;
            const auto filters = engine.enumerate_filters();
            record(current_stage, filters.hr);
            target_gate(Stage::target_after_enumeration);
            if (result.issue != Issue::none) break;
            if (filters.count == 0 || filters.count > kMaxFilters ||
                filters.total_filter_count > kMaxFilters ||
                filters.count > filters.total_filter_count) {
                block(Stage::enumerate_filters, Issue::filter_count_invalid);
                break;
            }
            std::uint32_t av_index = 0;
            std::size_t av_count = 0;
            for (std::size_t i = 0; i < filters.count; ++i) {
                const auto& filter = filters.records[i];
                if (filter.index >= filters.total_filter_count) {
                    block(Stage::enumerate_filters, Issue::filter_index_invalid);
                    break;
                }
                for (std::size_t j = 0; j < i; ++j) {
                    if (filters.records[j].index == filter.index)
                        block(Stage::enumerate_filters, Issue::filter_indices_duplicate);
                }
                if (filter.code == kAccessViolationCode) {
                    av_index = filter.index;
                    ++av_count;
                }
            }
            if (result.issue != Issue::none) break;
            if (av_count != 1) {
                block(Stage::enumerate_filters,
                      av_count == 0 ? Issue::av_missing : Issue::av_duplicate);
                break;
            }
            current_stage = Stage::register_command;
            const auto registration = engine.register_fixed_command();
            if (registration.execute_called) record(current_stage, registration.hr);
            else block(current_stage, Issue::call_not_observed);
            record_optional(Stage::register_flush, registration.flush_hresult);
            if (registration.callback_wrong_thread || registration.callback_invalid_text)
                block(Stage::register_command, Issue::callback_violation);
            target_gate(Stage::target_after_registration);
            if (result.issue != Issue::none) break;
            current_stage = Stage::getter_a;
            result.getter_a = engine.get_fixed_command(av_index);
            record(current_stage, result.getter_a.hr);
            target_gate(Stage::target_after_getter_a);
            if (result.issue != Issue::none) break;
            block(Stage::getter_a, detail::validate_getter(result.getter_a));
            if (result.issue != Issue::none) break;
            result.getter_a_valid = true;
            result.a_expected = detail::expected(result.getter_a);
            current_stage = Stage::display_sx;
            const auto display = engine.display_fixed_sx();
            result.output = display.output;
            record_optional(Stage::display_pre_flush, display.pre_flush_hresult);
            if (display.execute_called) record(Stage::display_sx, display.hr);
            else block(Stage::display_sx, Issue::call_not_observed);
            record_optional(Stage::display_post_flush, display.post_flush_hresult);
            if (display.callback_wrong_thread || display.callback_invalid_text)
                block(Stage::display_sx, Issue::callback_violation);
            target_gate(Stage::target_after_display);
            if (result.issue != Issue::none) break;
            block(Stage::display_sx, result.output.issue());
            if (result.issue != Issue::none) break;
            current_stage = Stage::getter_b;
            result.getter_b = engine.get_fixed_command(av_index);
            record(current_stage, result.getter_b.hr);
            target_gate(Stage::target_after_getter_b);
            if (result.issue != Issue::none) break;
            block(Stage::getter_b, detail::validate_getter(result.getter_b));
            if (result.issue != Issue::none) break;
            result.getter_b_valid = true;
            result.b_expected = detail::expected(result.getter_b);
            result.ab_stability = result.getter_a.reported_length ==
                result.getter_b.reported_length &&
                std::equal(result.getter_a.bytes.begin(), result.getter_a.bytes.begin() +
                           result.getter_a.reported_length, result.getter_b.bytes.begin())
                ? Comparison::equal : Comparison::different;
            if (result.ab_stability == Comparison::different)
                block(Stage::getter_b, Issue::getter_changed);
        } while (false);
    } catch (...) {
        block(current_stage, Issue::adapter_exception);
    }
    // Explicit finalization occurs once, also for thrown adapter calls. Adapter
    // RAII remains responsible for references if the adapter itself cannot run.
    result.cleanup = engine.close();
    if (result.cleanup.callback_violation)
        block(Stage::close, Issue::callback_violation);
    if (!result.cleanup.all_owned_release_calls_issued || result.cleanup.wrong_thread ||
        !result.cleanup.detach_hresult || *result.cleanup.detach_hresult != 0)
        block(Stage::close, Issue::cleanup_incomplete);
    if (result.issue == Issue::none) {
        result.observations_complete = true;
        result.stage = Stage::observations_complete;
    }
    return result;
}
}  // namespace issue110_filter_probe
#endif
