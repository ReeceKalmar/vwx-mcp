#pragma once

// Pure scheduling policy: no Win32, SDK, Python or document access.
namespace VwxBridge
{
    constexpr bool RunnerMayBeActive(unsigned long long entry,
                                     unsigned long long completion)
    {
        return entry != 0 && (completion == 0 || entry > completion);
    }

    // A private posted event is consumed once, before any synchronous host
    // menu invocation. Duplicate, stale and nested deliveries cannot execute.
    struct MenuBrokerState
    {
        using Token = unsigned long long;
        Token serial = 0;
        Token queuedToken = 0;
        bool active = false;

        constexpr bool CanQueue() const { return queuedToken == 0 && !active; }
        constexpr Token Reserve()
        {
            if (!CanQueue()) return 0;
            if (++serial == 0) ++serial;
            queuedToken = serial;
            return queuedToken;
        }
        constexpr void PostFailed(Token token)
        {
            if (token != 0 && token == queuedToken) queuedToken = 0;
        }
        // Call only after the private target was successfully destroyed.
        // Retain serial/active and the separate completion fence; a canceled
        // queued token must not latch a newly created broker or be reused.
        constexpr void TargetDestroyed() { queuedToken = 0; }
        constexpr bool BeginDelivery(Token token)
        {
            if (active || token == 0 || token != queuedToken) return false;
            queuedToken = 0;
            active = true;
            return true;
        }
        constexpr void EndDelivery() { active = false; }
    };

    struct PumpScheduleState
    {
        using Tick = unsigned long long;
        static constexpr Tick kAcknowledgeTimeoutMs = 2000;
        bool pending = false;
        bool timedOut = false;
        Tick postedAt = 0;
        Tick stampBefore = 0;
        Tick posted = 0;
        Tick foregroundPosts = 0;
        Tick backgroundPosts = 0;
        Tick acknowledged = 0;
        Tick timeouts = 0;

        constexpr bool CanPost() const { return !pending; }

        constexpr void Posted(Tick now, Tick completionStamp, bool foreground)
        {
            pending = true;
            timedOut = false;
            postedAt = now;
            stampBefore = completionStamp;
            ++posted;
            if (foreground) ++foregroundPosts;
            else ++backgroundPosts;
        }

        constexpr void Observe(Tick completionStamp, Tick now)
        {
            if (!pending) return;
            if (completionStamp != 0 && completionStamp != stampBefore) {
                pending = false;
                timedOut = false;
                ++acknowledged;
            }
            else if (!timedOut && now - postedAt >= kAcknowledgeTimeoutMs) {
                // A delayed posted message may still execute. Never repost it
                // simply because the runner has not yet been observed.
                timedOut = true;
                ++timeouts;
            }
        }
    };

}
