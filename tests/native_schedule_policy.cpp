// Compile-only tests execute the actual constexpr production scheduling policy.
#include "../native/Source/Bridge/PumpScheduleState.h"

constexpr bool OutstandingTriggerNeverTimesOutIntoReplay()
{
    VwxBridge::PumpScheduleState state;
    if (!state.CanPost()) return false;
    state.Posted(100, 42, false);
    if (state.CanPost() || !state.pending || state.posted != 1) return false;
    state.Observe(42, 2099);
    if (state.timedOut || state.CanPost()) return false;
    state.Observe(42, 2100);
    if (!state.timedOut || state.CanPost() || state.timeouts != 1) return false;
    state.Observe(42, 5000);
    return state.timeouts == 1 && !state.CanPost() && state.acknowledged == 0;
}

constexpr bool OnlyChangedNonzeroCompletionStampAcknowledges()
{
    VwxBridge::PumpScheduleState state;
    state.Observe(99, 1);
    if (state.acknowledged != 0) return false;
    state.Posted(100, 42, true);
    state.Observe(0, 101);
    if (!state.pending) return false;
    state.Observe(42, 102);
    if (!state.pending) return false;
    state.Observe(43, 103);
    if (!state.CanPost() || state.acknowledged != 1) return false;
    state.Observe(44, 104);
    return state.acknowledged == 1;
}

constexpr bool DelayedAcknowledgmentRecoversAndTracksForegroundSeparately()
{
    VwxBridge::PumpScheduleState state;
    state.Posted(100, 0, false);
    state.Observe(0, 2100);
    state.Observe(99, 2200);
    if (!state.CanPost() || state.timedOut || state.timeouts != 1) return false;
    state.Posted(2300, 99, true);
    state.Observe(100, 2301);
    return state.posted == 2 && state.acknowledged == 2
        && state.backgroundPosts == 1 && state.foregroundPosts == 1;
}

constexpr bool OuterRunnerMustCompleteBeforeAnotherTrigger()
{
    using VwxBridge::RunnerMayBeActive;
    return !RunnerMayBeActive(0, 0) && !RunnerMayBeActive(0, 50)
        && RunnerMayBeActive(50, 0) && RunnerMayBeActive(51, 50)
        && !RunnerMayBeActive(50, 50) && !RunnerMayBeActive(49, 50);
}

constexpr bool StaleDuplicateAndNestedBrokerMessagesCannotInvoke()
{
    VwxBridge::MenuBrokerState broker;
    if (broker.BeginDelivery(0) || broker.BeginDelivery(1)) return false;
    const auto first = broker.Reserve();
    if (!first || broker.CanQueue() || broker.Reserve() != 0) return false;
    if (broker.BeginDelivery(first + 1) || broker.queuedToken != first) return false;
    if (!broker.BeginDelivery(first) || !broker.active || broker.queuedToken != 0) return false;
    if (broker.BeginDelivery(first) || broker.BeginDelivery(0) || broker.CanQueue()) return false;
    if (broker.Reserve() != 0) return false;
    broker.EndDelivery();
    if (!broker.CanQueue() || broker.BeginDelivery(first)) return false;
    const auto second = broker.Reserve();
    if (second == 0 || second == first || broker.BeginDelivery(first)) return false;
    return broker.BeginDelivery(second);
}

constexpr bool FailedPostReleasesOnlyItsOwnUnqueuedToken()
{
    VwxBridge::MenuBrokerState broker;
    const auto token = broker.Reserve();
    broker.PostFailed(0);
    broker.PostFailed(token + 1);
    if (broker.CanQueue()) return false;
    broker.PostFailed(token);
    if (!broker.CanQueue() || broker.BeginDelivery(token)) return false;
    const auto next = broker.Reserve();
    broker.PostFailed(token);
    if (broker.queuedToken != next || !broker.BeginDelivery(next)) return false;
    broker.PostFailed(next);
    return broker.active && !broker.CanQueue();
}

constexpr bool TokenWrapDoesNotIssueZero()
{
    VwxBridge::MenuBrokerState broker;
    broker.serial = ~0ULL;
    const auto token = broker.Reserve();
    return token == 1 && broker.BeginDelivery(token);
}

constexpr bool DestroyedQueuedTargetPreservesFenceAndRejectsStaleTokensAfterReopen()
{
    VwxBridge::PumpScheduleState schedule;
    VwxBridge::MenuBrokerState broker;
    const auto canceled = broker.Reserve();
    schedule.Posted(100, 42, false);
    broker.TargetDestroyed();
    if (!broker.CanQueue() || broker.serial != canceled || broker.BeginDelivery(canceled)) return false;
    // Reopening alone never clears the uncertain completion fence.
    schedule.Observe(42, 3100);
    if (schedule.CanPost() || !schedule.timedOut || schedule.acknowledged != 0) return false;
    // An explicit/manual completion may legitimately release that fence.
    schedule.Observe(43, 3200);
    if (!schedule.CanPost()) return false;
    const auto fresh = broker.Reserve();
    if (fresh == canceled || !fresh || broker.BeginDelivery(canceled)) return false;
    if (!broker.BeginDelivery(fresh)) return false;
    // A nested close while invocation is active cannot release its guard.
    broker.TargetDestroyed();
    if (!broker.active || broker.CanQueue() || broker.serial != fresh) return false;
    broker.EndDelivery();
    return broker.CanQueue() && !broker.BeginDelivery(fresh);
}

constexpr bool BrokerReturnOrRejectionDoesNotAcknowledgeOrReplay()
{
    for (int outcome = 0; outcome < 3; ++outcome) {
        VwxBridge::PumpScheduleState schedule;
        VwxBridge::MenuBrokerState broker;
        const auto token = broker.Reserve();
        schedule.Posted(100, 42, false);
        schedule.Observe(42, 3000);
        if (!schedule.timedOut || !broker.BeginDelivery(token)) return false;
        // Return, pre-call rejection and C++ exception release only the broker
        // active flag, never the independent completion fence.
        broker.EndDelivery();
        if (schedule.CanPost() || !schedule.pending || broker.BeginDelivery(token)) return false;
        schedule.Observe(42, 9000);
        if (schedule.CanPost() || schedule.acknowledged != 0) return false;
        if (outcome == 0) {
            schedule.Observe(43, 9001);
            if (!schedule.CanPost() || schedule.acknowledged != 1) return false;
        }
    }
    return true;
}

static_assert(OutstandingTriggerNeverTimesOutIntoReplay());
static_assert(OnlyChangedNonzeroCompletionStampAcknowledges());
static_assert(DelayedAcknowledgmentRecoversAndTracksForegroundSeparately());
static_assert(OuterRunnerMustCompleteBeforeAnotherTrigger());
static_assert(StaleDuplicateAndNestedBrokerMessagesCannotInvoke());
static_assert(FailedPostReleasesOnlyItsOwnUnqueuedToken());
static_assert(TokenWrapDoesNotIssueZero());
static_assert(DestroyedQueuedTargetPreservesFenceAndRejectsStaleTokensAfterReopen());
static_assert(BrokerReturnOrRejectionDoesNotAcknowledgeOrReplay());
