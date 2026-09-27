#pragma once

#include <windows.h>
#include <cstdio>
#include <string>

namespace VwxBridge
{
    // Only the UI thread publishes these diagnostics. Readers see the previous
    // complete value until the complete replacement is closed and renamed.
    // A sharing violation or I/O failure keeps the previous value intact; the
    // existing freshness checks will reject it if publication remains blocked.
    inline bool WriteAtomicStatusFile(const std::wstring& path, const std::string& data)
    {
        if (path.empty() || data.empty()) return false;
        const std::wstring temporary = path + L".tmp";
        FILE* file = _wfopen(temporary.c_str(), L"wb");
        if (!file) return false;
        const bool written = fwrite(data.data(), 1, data.size(), file) == data.size();
        const bool closed = fclose(file) == 0;
        const bool published = written && closed &&
            MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING) != 0;
        if (!published) _wremove(temporary.c_str());
        return published;
    }
}
