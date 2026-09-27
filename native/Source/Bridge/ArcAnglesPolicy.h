#pragma once

#include <cmath>
#include <cstdint>

namespace VwxBridge::ArcAngles
{
    // Revision describes this private scripting ABI, not host compatibility.
    inline constexpr std::int32_t kNativeRevision = 1;
    inline constexpr short kHandleArgument = 25;
    inline constexpr short kRealArgument = 5;
    inline constexpr short kArcObjectType = 6;

    enum class Status : std::int32_t
    {
        Accepted = 1,       // The SDK call returned; geometry is not verified.
        InvalidContext = -1,
        InvalidArguments = -2,
        WrongObjectType = -3,
        NativeException = -4, // A mutation may have happened. Never replay.
        UnknownRoutine = -5
    };

    inline constexpr bool ArgumentTypesMatch(short handle, short start, short sweep)
    {
        return handle == kHandleArgument && start == kRealArgument && sweep == kRealArgument;
    }

    // Host is supplied by the scripting callback. There is no timer, queue,
    // replacement-object operation, or second setter attempt in this path.
    template<class Host, class Handle>
    Status SetAngles(Host& host, Handle handle, double startDegrees, double sweepDegrees)
    {
        if (!handle || !std::isfinite(startDegrees) || !std::isfinite(sweepDegrees))
            return Status::InvalidArguments;

        try
        {
            if (!host.ContextReady())
                return Status::InvalidContext;
            if (host.ObjectType(handle) != kArcObjectType)
                return Status::WrongObjectType;
            host.SetAngles(handle, startDegrees, sweepDegrees);
            return Status::Accepted;
        }
        catch (...)
        {
            return Status::NativeException;
        }
    }
}
