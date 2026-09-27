#pragma once

#include <cstdint>
#include <string>

namespace VwxBridge::DocumentTransition
{
    // The broker arms one synchronous Python menu invocation. Stage only
    // records intent there; End runs native document calls after it returns.
    bool BeginMenu(std::uint32_t uiThread, std::uint64_t invocation);
    void EndMenu(std::uint64_t invocation, bool returnedAndCompleted);
    std::int32_t Revision(std::uint32_t registrationThread);
    std::int32_t Stage(std::uint32_t registrationThread, const std::wstring& source,
                       const std::wstring& target, const std::wstring& request);
    std::string Status(std::uint32_t registrationThread);
}
