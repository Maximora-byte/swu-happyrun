// Software-only state machine tests. No Windows headers, DLLs, files or targets.
#include "scripts/diagnostics/issue110_filter_probe_core.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace p = issue110_filter_probe;
#define CHECK(expression) do { if (!(expression)) throw std::runtime_error( \
    std::string(__func__) + ": " + #expression); } while (false)

static p::GetterReply getter(const std::string& value = p::kIntendedCommand) {
    p::GetterReply reply;
    reply.hr = 0;
    reply.reported_length = static_cast<std::uint32_t>(value.size() + 1);
    std::copy(value.begin(), value.end(), reply.bytes.begin());
    reply.bytes[value.size()] = 0;
    return reply;
}

static p::DisplayReply display() {
    p::DisplayReply reply;
    reply.hr = 0;
    reply.execute_called = true;
    reply.pre_flush_hresult = 0;
    reply.post_flush_hresult = 0;
    reply.output.begin();
    const std::string text = "av - arbitrary unvalidated output\r\n";
    reply.output.append(p::OutputPhase::sx, text.data(), text.size());
    reply.output.finish();
    return reply;
}

class Fake final : public p::Engine {
public:
    std::vector<std::string> calls;
    std::vector<p::TargetReply> targets = std::vector<p::TargetReply>(
        6, p::TargetReply{0, p::TargetState::no_target});
    p::FilterReply filters;
    p::RegistrationReply registration;
    p::GetterReply a = getter();
    p::GetterReply b = getter();
    p::DisplayReply sx = display();
    p::CloseResult cleanup;
    std::size_t target_count = 0;
    std::size_t getter_count = 0;
    std::vector<std::uint32_t> indices;
    bool throw_registration = false;

    Fake() {
        registration.hr = 0;
        registration.execute_called = true;
        registration.flush_hresult = 0;
        filters.hr = 0;
        filters.total_filter_count = 19;
        filters.count = 2;
        filters.records[0] = {0x80000003u, 14};
        filters.records[1] = {p::kAccessViolationCode, 17};
        cleanup.all_owned_release_calls_issued = true;
        cleanup.detach_hresult = 0;
    }
    p::TargetReply no_target() override {
        calls.push_back("target");
        return targets.at(target_count++);
    }
    p::FilterReply enumerate_filters() override {
        calls.push_back("enumerate");
        return filters;
    }
    p::RegistrationReply register_fixed_command() override {
        calls.push_back("register");
        if (throw_registration) throw std::runtime_error("adapter failure");
        return registration;
    }
    p::GetterReply get_fixed_command(std::uint32_t index) override {
        calls.push_back(getter_count == 0 ? "get_a" : "get_b");
        indices.push_back(index);
        return getter_count++ == 0 ? a : b;
    }
    p::DisplayReply display_fixed_sx() override {
        calls.push_back("sx");
        return sx;
    }
    p::CloseResult close() noexcept override {
        calls.push_back("close");
        return cleanup;
    }
};

static void invariants(const Fake& fake, const p::Result& result) {
    CHECK(!result.execution_ready);
    CHECK(!result.passed);
    CHECK(result.display_comparison == p::DisplayComparison::format_unknown);
    CHECK(std::count(fake.calls.begin(), fake.calls.end(), "close") == 1);
    CHECK(fake.calls.back() == "close");
    CHECK(std::count(fake.calls.begin(), fake.calls.end(), "register") <= 1);
    CHECK(std::count(fake.calls.begin(), fake.calls.end(), "get_a") <= 1);
    CHECK(std::count(fake.calls.begin(), fake.calls.end(), "get_b") <= 1);
    CHECK(std::count(fake.calls.begin(), fake.calls.end(), "sx") <= 1);
}

static void fixed_order_and_limited_observation() {
    CHECK(std::string(p::kIntendedCommand) == "$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb");
    CHECK(std::string(p::kRegistrationCommand) ==
          "sxd -c2 \"$$>a<C:\\SWU_ISSUE110_SYNTHETIC\\terminal.cdb\" av");
    Fake fake;
    const auto result = p::run_probe(fake);
    invariants(fake, result);
    CHECK(result.observations_complete);
    CHECK(result.issue == p::Issue::none);
    CHECK(result.stage == p::Stage::observations_complete);
    CHECK((fake.calls == std::vector<std::string>{"target", "enumerate", "target",
        "register", "target", "get_a", "target", "sx", "target", "get_b", "target", "close"}));
    CHECK((fake.indices == std::vector<std::uint32_t>{17, 17}));
    CHECK(result.getter_a_valid && result.getter_b_valid);
    CHECK(result.a_expected == p::Comparison::equal);
    CHECK(result.b_expected == p::Comparison::equal);
    CHECK(result.ab_stability == p::Comparison::equal);
    CHECK(result.trace_count == 14);
    CHECK(result.cleanup.all_owned_release_calls_issued);
    CHECK(!result.cleanup.engine_disposal_confirmed);
    CHECK(result.cleanup.detach_hresult == 0);
}

static void target_gates_fail_closed() {
    const p::Stage expected[] = {p::Stage::target_before_enumeration,
        p::Stage::target_after_enumeration, p::Stage::target_after_registration,
        p::Stage::target_after_getter_a, p::Stage::target_after_display,
        p::Stage::target_after_getter_b};
    for (std::size_t position = 0; position < 6; ++position) {
        for (const auto state : {p::TargetState::target, p::TargetState::unknown}) {
            Fake fake;
            fake.targets[position].state = state;
            const auto result = p::run_probe(fake);
            invariants(fake, result);
            CHECK(!result.observations_complete);
            CHECK(result.stage == expected[position]);
            CHECK(result.issue == p::Issue::target_not_absent);
            CHECK(fake.target_count == position + 1);
            CHECK(fake.calls.size() == 2 * position + 2);
        }
        for (const auto hr : {p::HResult{1}, p::HResult{-2147467259}}) {
            Fake fake;
            fake.targets[position].hr = hr;
            const auto result = p::run_probe(fake);
            invariants(fake, result);
            CHECK(!result.observations_complete);
            CHECK(result.stage == expected[position]);
            CHECK(result.issue == p::Issue::call_not_s_ok);
            CHECK(result.trace[result.trace_count - 1].hr == hr);
        }
    }
}

static void every_meaningful_hresult_is_exact() {
    const p::Stage expected[] = {p::Stage::enumerate_filters, p::Stage::register_command,
        p::Stage::getter_a, p::Stage::display_sx, p::Stage::getter_b};
    for (std::size_t position = 0; position < 5; ++position) {
        for (const auto hr : {p::HResult{1}, p::HResult{-2147467259}}) {
            Fake fake;
            if (position == 0) fake.filters.hr = hr;
            if (position == 1) fake.registration.hr = hr;
            if (position == 2) fake.a.hr = hr;
            if (position == 3) fake.sx.hr = hr;
            if (position == 4) fake.b.hr = hr;
            const auto result = p::run_probe(fake);
            invariants(fake, result);
            CHECK(!result.observations_complete);
            CHECK(result.stage == expected[position]);
            CHECK(result.issue == p::Issue::call_not_s_ok);
            bool found = false;
            for (std::size_t i = 0; i < result.trace_count; ++i) {
                if (result.trace[i].stage == expected[position]) {
                    CHECK(result.trace[i].hr == hr);
                    found = true;
                }
            }
            CHECK(found);
            CHECK(fake.target_count == position + 2);
            CHECK(fake.calls.size() == 2 * position + 4);
        }
    }
    Fake double_failure;
    double_failure.registration.hr = 1;
    double_failure.targets[2].hr = -42;
    const auto result = p::run_probe(double_failure);
    CHECK(result.stage == p::Stage::register_command);
    CHECK(result.trace[result.trace_count - 3].hr == 1);
    CHECK(result.trace[result.trace_count - 1].hr == -42);
}

static void invalid_filters_never_register() {
    for (unsigned scenario = 0; scenario < 8; ++scenario) {
        Fake fake;
        p::Issue expected = p::Issue::filter_count_invalid;
        switch (scenario) {
        case 0: fake.filters.count = p::kMaxFilters + 1; break;
        case 1: fake.filters.total_filter_count = p::kMaxFilters + 1; break;
        case 2: fake.filters.total_filter_count = 1; break;
        case 3: fake.filters.records[1].index = 19;
            expected = p::Issue::filter_index_invalid; break;
        case 4: fake.filters.records[1].index = 14;
            expected = p::Issue::filter_indices_duplicate; break;
        case 5: fake.filters.records[1].code = 0;
            expected = p::Issue::av_missing; break;
        case 6: fake.filters.records[0].code = p::kAccessViolationCode;
            expected = p::Issue::av_duplicate; break;
        case 7: fake.filters.count = 0; break;
        }
        const auto result = p::run_probe(fake);
        invariants(fake, result);
        CHECK(!result.observations_complete);
        CHECK(result.stage == p::Stage::enumerate_filters);
        CHECK(result.issue == expected);
        CHECK(fake.calls.size() == 4);
    }
}

static void getters_are_exact_bounded_ascii() {
    for (unsigned which = 0; which < 2; ++which) {
        for (unsigned scenario = 0; scenario < 8; ++scenario) {
            Fake fake;
            auto& reply = which == 0 ? fake.a : fake.b;
            p::Issue expected = p::Issue::getter_length_invalid;
            switch (scenario) {
            case 0: reply.reported_length = 0; break;
            case 1: reply.reported_length = p::kGetterCapacity + 1; break;
            case 2: reply.bytes[reply.reported_length - 1] = 'X';
                expected = p::Issue::getter_terminator_missing; break;
            case 3: reply.bytes[2] = 0;
                expected = p::Issue::getter_embedded_nul; break;
            case 4: reply.bytes[2] = 0x80;
                expected = p::Issue::getter_non_ascii; break;
            case 5: reply.bytes[2] = '\n';
                expected = p::Issue::getter_non_ascii; break;
            case 6: reply.bytes[2] = 0x7f;
                expected = p::Issue::getter_non_ascii; break;
            case 7: reply.reported_length -= 1;
                expected = p::Issue::getter_terminator_missing; break;
            }
            const auto result = p::run_probe(fake);
            invariants(fake, result);
            CHECK(!result.observations_complete);
            CHECK(result.issue == expected);
            CHECK(result.stage == (which == 0 ? p::Stage::getter_a : p::Stage::getter_b));
            CHECK(which == 0 ? !result.getter_a_valid : !result.getter_b_valid);
            CHECK(fake.getter_count == which + 1);
        }
    }
    for (const auto length : {std::size_t{0}, p::kGetterCapacity - 1}) {
        Fake fake;
        fake.a = getter(std::string(length, 'x'));
        fake.b = fake.a;
        const auto result = p::run_probe(fake);
        invariants(fake, result);
        CHECK(result.observations_complete);
        CHECK(result.a_expected == p::Comparison::different);
        CHECK(result.ab_stability == p::Comparison::equal);
    }
}

static void comparisons_are_observations_not_pass() {
    Fake fake;
    fake.a = getter("different but valid ASCII");
    const auto result = p::run_probe(fake);
    invariants(fake, result);
    CHECK(!result.observations_complete);
    CHECK(result.stage == p::Stage::getter_b);
    CHECK(result.issue == p::Issue::getter_changed);
    CHECK(result.a_expected == p::Comparison::different);
    CHECK(result.b_expected == p::Comparison::equal);
    CHECK(result.ab_stability == p::Comparison::different);
    CHECK(result.getter_a.bytes == fake.a.bytes);
    CHECK(result.getter_b.bytes == fake.b.bytes);
    CHECK(result.getter_a_valid && result.getter_b_valid);

    Fake stable_discrepancy;
    stable_discrepancy.a = getter("same unexpected command");
    stable_discrepancy.b = stable_discrepancy.a;
    const auto stable = p::run_probe(stable_discrepancy);
    invariants(stable_discrepancy, stable);
    CHECK(stable.observations_complete);
    CHECK(stable.issue == p::Issue::none);
    CHECK(stable.a_expected == p::Comparison::different);
    CHECK(stable.b_expected == p::Comparison::different);
    CHECK(stable.ab_stability == p::Comparison::equal);
}

static void malformed_output_is_blocked_without_parsing() {
    for (unsigned scenario = 0; scenario < 8; ++scenario) {
        Fake fake;
        fake.sx.output = p::BoundedOutput{};
        auto& output = fake.sx.output;
        p::Issue expected = p::Issue::output_ambiguous;
        switch (scenario) {
        case 0: output.begin(); break;
        case 1: output.begin(); output.append(p::OutputPhase::other, "x", 1);
            output.finish(); break;
        case 2: output.append(p::OutputPhase::sx, "x", 1); output.finish(); break;
        case 3: output.begin(); output.finish();
            output.append(p::OutputPhase::sx, "x", 1); break;
        case 4: output.begin(); output.begin(); output.finish(); break;
        case 5: { output.begin(); const std::string large(p::kOutputCapacity + 1, 'x');
            output.append(p::OutputPhase::sx, large.data(), large.size());
            output.finish(); expected = p::Issue::output_overflow; break; }
        case 6: output.begin(); output.append(p::OutputPhase::sx, "a\0b", 3);
            output.finish(); expected = p::Issue::output_non_ascii; break;
        case 7: output.begin(); output.append(p::OutputPhase::sx, "\xff", 1);
            output.finish(); expected = p::Issue::output_non_ascii; break;
        }
        if (scenario == 0) expected = p::Issue::output_incomplete;
        const auto result = p::run_probe(fake);
        invariants(fake, result);
        CHECK(!result.observations_complete);
        CHECK(result.stage == p::Stage::display_sx);
        CHECK(result.issue == expected);
        CHECK(fake.getter_count == 1);
    }
    // A complete bounded output is still not an understood grammar.
    Fake fake;
    fake.sx.output = p::BoundedOutput{};
    fake.sx.output.begin();
    const std::string exact(p::kOutputCapacity, 'x');
    fake.sx.output.append(p::OutputPhase::sx, exact.data(), exact.size());
    fake.sx.output.finish();
    const auto result = p::run_probe(fake);
    invariants(fake, result);
    CHECK(result.observations_complete);
    CHECK(result.output.size() == p::kOutputCapacity);
}

static void cleanup_is_not_engine_disposal() {
    Fake fake;
    fake.cleanup.all_owned_release_calls_issued = false;
    const auto result = p::run_probe(fake);
    invariants(fake, result);
    CHECK(!result.observations_complete);
    CHECK(result.stage == p::Stage::close);
    CHECK(result.issue == p::Issue::cleanup_incomplete);
    Fake detach_failure;
    detach_failure.cleanup.detach_hresult = 1;
    const auto detached = p::run_probe(detach_failure);
    invariants(detach_failure, detached);
    CHECK(!detached.observations_complete);
    CHECK(detached.cleanup.detach_hresult == 1);
    Fake absent_detach;
    absent_detach.cleanup.detach_hresult.reset();
    const auto absent = p::run_probe(absent_detach);
    CHECK(!absent.observations_complete);
    Fake thrown;
    thrown.throw_registration = true;
    const auto caught = p::run_probe(thrown);
    invariants(thrown, caught);
    CHECK(!caught.observations_complete);
    CHECK(caught.stage == p::Stage::register_command);
    CHECK(caught.issue == p::Issue::adapter_exception);
}

static void flush_and_callback_evidence_is_preserved() {
    for (unsigned where = 0; where < 3; ++where) {
        for (const auto hr : {p::HResult{1}, p::HResult{-71}}) {
            Fake fake;
            p::Stage expected = p::Stage::register_flush;
            if (where == 0) fake.registration.flush_hresult = hr;
            if (where == 1) {
                fake.sx.pre_flush_hresult = hr;
                fake.sx.execute_called = false;
                fake.sx.post_flush_hresult.reset();
                expected = p::Stage::display_pre_flush;
            }
            if (where == 2) {
                fake.sx.post_flush_hresult = hr;
                expected = p::Stage::display_post_flush;
            }
            const auto result = p::run_probe(fake);
            invariants(fake, result);
            CHECK(!result.observations_complete);
            CHECK(result.issue == p::Issue::call_not_s_ok);
            CHECK(result.stage == expected);
            bool found = false;
            for (std::size_t i = 0; i < result.trace_count; ++i) {
                if (result.trace[i].stage == expected) {
                    CHECK(result.trace[i].hr == hr);
                    found = true;
                }
                if (where == 1) CHECK(result.trace[i].stage != p::Stage::display_sx);
            }
            CHECK(found);
        }
    }
    for (unsigned where = 0; where < 5; ++where) {
        Fake fake;
        if (where == 0) fake.registration.execute_called = false;
        if (where == 1) fake.registration.flush_hresult.reset();
        if (where == 2) fake.sx.pre_flush_hresult.reset();
        if (where == 3) fake.sx.execute_called = false;
        if (where == 4) fake.sx.post_flush_hresult.reset();
        const auto result = p::run_probe(fake);
        invariants(fake, result);
        CHECK(!result.observations_complete);
        CHECK(result.issue == p::Issue::call_not_observed);
    }
    for (unsigned where = 0; where < 6; ++where) {
        Fake fake;
        if (where == 0) fake.registration.callback_wrong_thread = true;
        if (where == 1) fake.registration.callback_invalid_text = true;
        if (where == 2) fake.sx.callback_wrong_thread = true;
        if (where == 3) fake.sx.callback_invalid_text = true;
        if (where == 4) fake.cleanup.wrong_thread = true;
        if (where == 5) fake.cleanup.callback_violation = true;
        const auto result = p::run_probe(fake);
        invariants(fake, result);
        CHECK(!result.observations_complete);
        CHECK(result.issue == p::Issue::callback_violation ||
              result.issue == p::Issue::cleanup_incomplete);
    }
    Fake fake;
    fake.cleanup.control_release_return = 2;
    fake.cleanup.client_release_return = 1;
    fake.cleanup.callback_release_return = 0;
    const auto result = p::run_probe(fake);
    invariants(fake, result);
    CHECK(result.observations_complete);
    CHECK(result.cleanup.control_release_return == 2);
    CHECK(result.cleanup.client_release_return == 1);
    CHECK(result.cleanup.callback_release_return == 0);
    CHECK(!result.cleanup.engine_disposal_confirmed);
}

static void empty_display_is_not_complete() {
    Fake fake;
    fake.sx.output = p::BoundedOutput{};
    fake.sx.output.begin();
    fake.sx.output.finish();
    const auto result = p::run_probe(fake);
    invariants(fake, result);
    CHECK(!result.observations_complete);
    CHECK(result.issue == p::Issue::output_incomplete);
    CHECK(result.stage == p::Stage::display_sx);
    CHECK(fake.getter_count == 1);
}

static void bounded_output_rejects_invalid_lifecycle_and_chunks() {
    p::BoundedOutput exact;
    exact.begin();
    const std::string first(p::kOutputCapacity - 1, 'A');
    exact.append(p::OutputPhase::sx, first.data(), first.size());
    exact.append(p::OutputPhase::sx, "Z", 1);
    exact.finish();
    CHECK(exact.issue() == p::Issue::none);
    CHECK(exact.size() == p::kOutputCapacity);
    CHECK(exact.data()[0] == 'A' && exact.data()[p::kOutputCapacity - 1] == 'Z');
    for (unsigned scenario = 0; scenario < 5; ++scenario) {
        p::BoundedOutput output;
        switch (scenario) {
        case 0: output.begin(); output.append(p::OutputPhase::sx, nullptr, 1);
            output.finish(); break;
        case 1: output.finish(); break;
        case 2: output.begin(); output.append(p::OutputPhase::sx, "x", 1);
            output.finish(); output.finish(); break;
        case 3: output.begin(); output.append(p::OutputPhase::sx, "x", 1);
            output.finish(); output.begin(); break;
        case 4: output.begin(); output.append(p::OutputPhase::other, nullptr, 0);
            output.finish(); break;
        }
        CHECK(output.issue() == p::Issue::output_ambiguous);
    }
    p::BoundedOutput overflow;
    overflow.begin();
    overflow.append(p::OutputPhase::sx, first.data(), first.size());
    overflow.append(p::OutputPhase::sx, "YZ", 2);
    overflow.finish();
    CHECK(overflow.issue() == p::Issue::output_overflow);
    CHECK(overflow.size() <= p::kOutputCapacity);
}

int main() {
    try {
        empty_display_is_not_complete();
        bounded_output_rejects_invalid_lifecycle_and_chunks();
        flush_and_callback_evidence_is_preserved();
        fixed_order_and_limited_observation();
        target_gates_fail_closed();
        every_meaningful_hresult_is_exact();
        invalid_filters_never_register();
        getters_are_exact_bounded_ascii();
        comparisons_are_observations_not_pass();
        malformed_output_is_blocked_without_parsing();
        cleanup_is_not_engine_disposal();
        std::cout << "portable fake-engine checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
