#ifndef SWU_ISSUE110_FILTER_CAPSULE_HPP
#define SWU_ISSUE110_FILTER_CAPSULE_HPP

// Portable private protocol only. No OS calls, DbgEng, file paths to open, or main.
// Inputs are confirmed byte spans, not getter scratch buffers. All string_views
// must remain valid and unchanged during this synchronous two-pass encoding.
#include "issue110_filter_probe_core.hpp"
#include <array>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string_view>

namespace issue110_filter_capsule {
inline constexpr std::size_t kCapsuleLimit = 262144;
inline constexpr std::size_t kGetterLimit = 4096;
inline constexpr std::size_t kSxLimit = 65536;
inline constexpr std::size_t kPathLimit = 8192;

enum class Stage {
    not_started, target_before_enumeration, enumerate_filters, target_after_enumeration,
    register_command, register_flush, target_after_registration, getter_a,
    target_after_getter_a, display_pre_flush, display_sx, display_post_flush,
    target_after_display, getter_b, target_after_getter_b, close, observations_complete,
    validate_request, verify_stage, initialize_search, inspect_modules, load_engine,
    validate_modules, create_engine
};
enum class Issue {
    none, call_not_s_ok, call_not_observed, callback_violation, target_not_absent,
    filter_count_invalid, filter_index_invalid, filter_indices_duplicate, av_missing,
    av_duplicate, getter_length_invalid, getter_terminator_missing, getter_embedded_nul,
    getter_non_ascii, getter_changed, output_incomplete, output_ambiguous, output_overflow,
    output_non_ascii, cleanup_incomplete, adapter_exception, invalid_request,
    loader_blocked, engine_creation_failed
};
enum class Comparison { not_observed, equal, different };
enum class Association { not_observed, associated, ambiguous };
enum class EncodeError { none, invalid_input, too_large, sink_failure };

struct GetterInput {
    bool valid = false;
    std::optional<std::int32_t> hresult{};
    std::optional<std::uint32_t> reported_length{};
    // Include the confirmed terminating NUL for a valid getter, and nothing
    // for an invalid getter, even when a reported length happens to be in range.
    std::string_view bytes{};
};
struct SxInput {
    std::string_view bytes{};
    bool overflow = false;
    Association association = Association::not_observed;
};
struct HResultObservation { Stage stage = Stage::not_started; std::int32_t hresult = 0; };
struct ReleaseInput {
    bool all_owned_release_calls_issued = false;
    bool engine_disposal_confirmed = false;
    std::optional<std::int32_t> detach_hresult{};
    std::optional<std::uint32_t> control_release_return{};
    std::optional<std::uint32_t> client_release_return{};
    std::optional<std::uint32_t> callback_release_return{};
    bool wrong_thread = false;
    bool callback_violation = false;
};
struct CapsuleInput {
    std::string_view nonce{};
    std::uint32_t child_pid = 0;
    Stage stage = Stage::not_started;
    Issue issue = Issue::none;
    bool engine_creation_attempted = false;
    bool observations_complete = false;
    GetterInput getter_a{};
    GetterInput getter_b{};
    SxInput sx{};
    Comparison a_expected = Comparison::not_observed;
    Comparison b_expected = Comparison::not_observed;
    Comparison ab_stability = Comparison::not_observed;
    std::array<HResultObservation, 32> hresult_trace{};
    std::size_t trace_count = 0;
    // Private lossless UTF-16LE byte spans, not decoded JSON path strings.
    std::array<std::string_view, 16> module_paths_utf16le{};
    std::size_t module_path_count = 0;
    ReleaseInput release{};
};
class ByteSink {
public:
    virtual ~ByteSink() = default;
    // true confirms the entire append. false/throw ends encoding, with no retry.
    // A sink may have partially written before failure: bytes_written counts
    // confirmed bytes only, never proves the actual file length or durability.
    virtual bool append(const char* data, std::size_t size) = 0;
};
struct EncodeResult {
    bool complete = false;
    std::size_t bytes_written = 0;
    EncodeError error = EncodeError::none;
};

namespace detail {
inline constexpr std::array<std::string_view, 24> stages{{
    "not_started", "target_before_enumeration", "enumerate_filters", "target_after_enumeration",
    "register_command", "register_flush", "target_after_registration", "getter_a",
    "target_after_getter_a", "display_pre_flush", "display_sx", "display_post_flush",
    "target_after_display", "getter_b", "target_after_getter_b", "close", "observations_complete",
    "validate_request", "verify_stage", "initialize_search", "inspect_modules", "load_engine",
    "validate_modules", "create_engine"
}};
inline constexpr std::array<std::string_view, 24> issues{{
    "none", "call_not_s_ok", "call_not_observed", "callback_violation", "target_not_absent",
    "filter_count_invalid", "filter_index_invalid", "filter_indices_duplicate", "av_missing",
    "av_duplicate", "getter_length_invalid", "getter_terminator_missing", "getter_embedded_nul",
    "getter_non_ascii", "getter_changed", "output_incomplete", "output_ambiguous", "output_overflow",
    "output_non_ascii", "cleanup_incomplete", "adapter_exception", "invalid_request",
    "loader_blocked", "engine_creation_failed"
}};
inline constexpr std::array<std::string_view, 3> comparisons{{"not_observed", "equal", "different"}};
inline constexpr std::array<std::string_view, 3> associations{{"not_observed", "associated", "ambiguous"}};
inline constexpr char hex_digits[] = "0123456789abcdef";

template<class Enum, std::size_t N>
inline std::string_view name(Enum value, const std::array<std::string_view, N>& names) {
    const auto index = static_cast<std::size_t>(value);
    return index < N ? names[index] : std::string_view{};
}
inline bool valid_getter(const GetterInput& getter) {
    if (getter.bytes.size() > kGetterLimit) return false;
    if (!getter.valid) return getter.bytes.empty();
    if (!getter.hresult || *getter.hresult != 0 || !getter.reported_length ||
        *getter.reported_length != getter.bytes.size() || getter.bytes.empty() ||
        getter.bytes.back() != '\0') return false;
    for (std::size_t i = 0; i + 1 < getter.bytes.size(); ++i) {
        const auto c = static_cast<unsigned char>(getter.bytes[i]);
        if (c < 0x20 || c > 0x7e) return false;
    }
    return true;
}
inline Comparison expected(const GetterInput& getter) {
    if (!getter.valid) return Comparison::not_observed;
    constexpr char command[] = "$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb";
    return getter.bytes == std::string_view(command, sizeof(command))
        ? Comparison::equal : Comparison::different;
}
inline bool ascii_output(std::string_view bytes) {
    for (const auto raw : bytes) {
        const auto c = static_cast<unsigned char>(raw);
        if (!((c >= 0x20 && c <= 0x7e) || c == 9 || c == 10 || c == 13)) return false;
    }
    return true;
}
inline bool valid(const CapsuleInput& input) {
    if (input.nonce.size() != 32 || input.child_pid == 0) return false;
    for (char c : input.nonce)
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    if (name(input.stage, stages).empty() || name(input.issue, issues).empty() ||
        name(input.sx.association, associations).empty() ||
        !valid_getter(input.getter_a) || !valid_getter(input.getter_b) ||
        input.sx.bytes.size() > kSxLimit || input.trace_count > input.hresult_trace.size() ||
        input.module_path_count > input.module_paths_utf16le.size() ||
        input.release.engine_disposal_confirmed) return false;
    const auto stability = input.getter_a.valid && input.getter_b.valid
        ? (input.getter_a.bytes == input.getter_b.bytes ? Comparison::equal : Comparison::different)
        : Comparison::not_observed;
    if (input.a_expected != expected(input.getter_a) || input.b_expected != expected(input.getter_b) ||
        input.ab_stability != stability) return false;
    for (std::size_t i = 0; i < input.trace_count; ++i)
        if (name(input.hresult_trace[i].stage, stages).empty()) return false;
    for (std::size_t i = 0; i < input.module_path_count; ++i) {
        const auto size = input.module_paths_utf16le[i].size();
        if (size > kPathLimit || size % 2 != 0) return false;
    }
    return !input.observations_complete ||
        (input.engine_creation_attempted && input.stage == Stage::observations_complete &&
         input.issue == Issue::none && input.getter_a.valid && input.getter_b.valid &&
         stability == Comparison::equal && !input.sx.bytes.empty() && !input.sx.overflow &&
         input.sx.association == Association::associated && ascii_output(input.sx.bytes) &&
         input.release.detach_hresult && *input.release.detach_hresult == 0 &&
         input.release.all_owned_release_calls_issued && !input.release.wrong_thread &&
         !input.release.callback_violation);
}

// The first pass is a bounded counter, with no output or allocation. The second
// pass writes only after the complete size and all inputs have been checked.
class Writer {
public:
    explicit Writer(ByteSink* sink, std::size_t limit) : sink_(sink), limit_(limit) {}
    std::size_t size = 0;
    bool ok = true;
    void text(std::string_view data) {
        if (!ok) return;
        if (data.size() > limit_ - size) { ok = false; return; }
        if (sink_) {
            try {
                if (!sink_->append(data.data(), data.size())) { ok = false; return; }
            } catch (...) { ok = false; return; }
        }
        size += data.size();
    }
    void quoted(std::string_view data) { text("\""); text(data); text("\""); }
    void boolean(bool value) { text(value ? "true" : "false"); }
    template<class T> void number(T value) {
        std::array<char, 32> buffer{};
        const auto converted = std::to_chars(buffer.data(), buffer.data() + buffer.size(), value);
        if (converted.ec != std::errc{}) { ok = false; return; }
        text(std::string_view(buffer.data(), static_cast<std::size_t>(converted.ptr - buffer.data())));
    }
    template<class T> void nullable(std::optional<T> value) {
        if (value) number(*value); else text("null");
    }
    void hex(std::string_view bytes) {
        text("\"");
        std::array<char, 256> buffer{};
        for (std::size_t offset = 0; offset < bytes.size() && ok;) {
            std::size_t count = 0;
            while (offset < bytes.size() && count < buffer.size()) {
                const auto value = static_cast<unsigned char>(bytes[offset++]);
                buffer[count++] = hex_digits[value >> 4];
                buffer[count++] = hex_digits[value & 15];
            }
            text(std::string_view(buffer.data(), count));
        }
        text("\"");
    }
private:
    ByteSink* sink_;
    std::size_t limit_;
};
inline void getter(Writer& w, const GetterInput& input) {
    w.text("{\"valid\":"); w.boolean(input.valid);
    w.text(",\"hresult\":"); w.nullable(input.hresult);
    w.text(",\"reported_length\":"); w.nullable(input.reported_length);
    w.text(",\"bytes_hex\":"); w.hex(input.bytes); w.text("}");
}
inline void body(Writer& w, const CapsuleInput& i) {
    w.text("{\"schema\":\"swu.issue110.filter-capsule.v1\",\"mode\":\"fixed_no_target\",\"nonce\":");
    w.quoted(i.nonce); w.text(",\"child_pid\":"); w.number(i.child_pid);
    w.text(",\"stage\":"); w.quoted(name(i.stage, stages));
    w.text(",\"issue\":"); w.quoted(name(i.issue, issues));
    w.text(",\"engine_creation_attempted\":"); w.boolean(i.engine_creation_attempted);
    w.text(",\"observations_complete\":"); w.boolean(i.observations_complete);
    w.text(",\"getter_a\":"); getter(w, i.getter_a);
    w.text(",\"getter_b\":"); getter(w, i.getter_b);
    w.text(",\"sx\":{\"bytes_hex\":"); w.hex(i.sx.bytes);
    w.text(",\"overflow\":"); w.boolean(i.sx.overflow);
    w.text(",\"association\":"); w.quoted(name(i.sx.association, associations)); w.text("}");
    w.text(",\"a_expected\":"); w.quoted(name(i.a_expected, comparisons));
    w.text(",\"b_expected\":"); w.quoted(name(i.b_expected, comparisons));
    w.text(",\"ab_stability\":"); w.quoted(name(i.ab_stability, comparisons));
    w.text(",\"hresult_trace\":[");
    for (std::size_t n = 0; n < i.trace_count; ++n) {
        if (n) w.text(",");
        w.text("{\"stage\":"); w.quoted(name(i.hresult_trace[n].stage, stages));
        w.text(",\"hresult\":"); w.number(i.hresult_trace[n].hresult); w.text("}");
    }
    w.text("],\"module_paths_utf16le_hex\":[");
    for (std::size_t n = 0; n < i.module_path_count; ++n) {
        if (n) w.text(",");
        w.hex(i.module_paths_utf16le[n]);
    }
    w.text("],\"release\":{\"all_owned_release_calls_issued\":");
    w.boolean(i.release.all_owned_release_calls_issued);
    w.text(",\"engine_disposal_confirmed\":"); w.boolean(i.release.engine_disposal_confirmed);
    w.text(",\"detach_hresult\":"); w.nullable(i.release.detach_hresult);
    w.text(",\"control_release_return\":"); w.nullable(i.release.control_release_return);
    w.text(",\"client_release_return\":"); w.nullable(i.release.client_release_return);
    w.text(",\"callback_release_return\":"); w.nullable(i.release.callback_release_return);
    w.text(",\"wrong_thread\":"); w.boolean(i.release.wrong_thread);
    w.text(",\"callback_violation\":"); w.boolean(i.release.callback_violation); w.text("}}");
}
}  // namespace detail

inline EncodeResult encode_capsule(const CapsuleInput& input, ByteSink& sink) {
    if (!detail::valid(input)) return {false, 0, EncodeError::invalid_input};
    detail::Writer counter(nullptr, kCapsuleLimit - 30);
    detail::body(counter, input);
    if (!counter.ok) return {false, 0, EncodeError::too_large};
    std::array<char, 8> length{};
    auto remaining = counter.size;
    for (std::size_t n = length.size(); n > 0; --n) {
        length[n - 1] = detail::hex_digits[remaining & 15];
        remaining >>= 4;
    }
    detail::Writer writer(&sink, kCapsuleLimit);
    writer.text("SWU110FP1\n");
    writer.text(std::string_view(length.data(), length.size())); writer.text("\n");
    detail::body(writer, input); writer.text("\nSWU110END\n");
    return {writer.ok, writer.size, writer.ok ? EncodeError::none : EncodeError::sink_failure};
}

// Synchronous projection from the unchanged core. Views never escape encoding;
// invalid getters carry no scratch-buffer bytes even if reported_length is set.
inline ReleaseInput release_input(const issue110_filter_probe::CloseResult& value) {
    return {value.all_owned_release_calls_issued, value.engine_disposal_confirmed,
            value.detach_hresult, value.control_release_return, value.client_release_return,
            value.callback_release_return, value.wrong_thread, value.callback_violation};
}
inline EncodeResult write_probe_capsule(const issue110_filter_probe::Result& result,
                                       std::string_view nonce, std::uint32_t pid,
                                       bool engine_attempted, ByteSink& sink,
                                       const std::array<std::string_view, 16>& module_paths = {},
                                       std::size_t module_count = 0) noexcept {
    CapsuleInput input;
    input.nonce = nonce;
    input.child_pid = pid;
    // These shared-prefix enum orders are pinned below, not independent guesses.
    static_assert(static_cast<unsigned>(Stage::observations_complete) ==
                  static_cast<unsigned>(issue110_filter_probe::Stage::observations_complete));
    static_assert(static_cast<unsigned>(Issue::adapter_exception) ==
                  static_cast<unsigned>(issue110_filter_probe::Issue::adapter_exception));
    input.stage = static_cast<Stage>(result.stage);
    input.issue = static_cast<Issue>(result.issue);
    input.engine_creation_attempted = engine_attempted;
    input.observations_complete = result.observations_complete;
    if (result.trace_count > result.trace.size()) return {false, 0, EncodeError::invalid_input};
    const auto getter = [&result](issue110_filter_probe::Stage stage, bool confirmed,
                                  const issue110_filter_probe::GetterReply& value) {
        // The core records this stage only after get_fixed_command returned.
        // Defaults and a thrown call are not observed HRESULT/length facts.
        bool returned = false;
        for (std::size_t i = 0; i < result.trace_count; ++i)
            if (result.trace[i].stage == stage) returned = true;
        if (!returned) return GetterInput{};
        return GetterInput{confirmed, value.hr, value.reported_length,
            confirmed && value.reported_length <= value.bytes.size()
                ? std::string_view(reinterpret_cast<const char*>(value.bytes.data()),
                                   value.reported_length) : std::string_view{}};
    };
    input.getter_a = getter(issue110_filter_probe::Stage::getter_a,
                            result.getter_a_valid, result.getter_a);
    input.getter_b = getter(issue110_filter_probe::Stage::getter_b,
                            result.getter_b_valid, result.getter_b);
    input.a_expected = static_cast<Comparison>(result.a_expected);
    input.b_expected = static_cast<Comparison>(result.b_expected);
    input.ab_stability = static_cast<Comparison>(result.ab_stability);
    const auto output_issue = result.output.issue();
    input.sx = {std::string_view(result.output.data(), result.output.size()),
                output_issue == issue110_filter_probe::Issue::output_overflow,
                output_issue == issue110_filter_probe::Issue::none ? Association::associated :
                output_issue == issue110_filter_probe::Issue::output_ambiguous
                    ? Association::ambiguous : Association::not_observed};
    input.trace_count = result.trace_count;
    for (std::size_t i = 0; i < input.trace_count; ++i)
        input.hresult_trace[i] = {static_cast<Stage>(result.trace[i].stage), result.trace[i].hr};
    input.module_paths_utf16le = module_paths;
    input.module_path_count = module_count;
    input.release = release_input(result.cleanup);
    return encode_capsule(input, sink);
}

}  // namespace issue110_filter_capsule
#endif
