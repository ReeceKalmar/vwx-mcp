#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace VwxBridge::Maintenance
{
    inline constexpr std::int32_t kRevision = 1;
    enum class Status : std::int32_t
    {
        Accepted = 1,
        InvalidContext = -101,
        InvalidArguments = -102,
        InventoryUnavailable = -103,
        UnsafeDocuments = -104,
        PathMismatch = -105,
        WorkingFile = -106,
        SaveFailed = -107,
        DocumentChanged = -108,
        NativeException = -109
    };

    struct Document
    {
        std::wstring path;
        std::int32_t fileRef = -1;
        bool active = false;
        bool inMemoryOnly = true;
    };
    using Documents = std::vector<Document>;

    inline bool IsAsciiLetter(wchar_t value)
    {
        return (value >= L'A' && value <= L'Z') || (value >= L'a' && value <= L'z');
    }

    // Lexical Windows normalization only. No current directory, environment
    // expansion, device paths, alternate streams, wildcards or path suffix
    // matching. Host comparison supplies Windows ordinal case folding.
    inline bool NormalizeVwxPath(const std::wstring& input, std::wstring& result)
    {
        result.clear();
        if (input.empty() || input.size() > 32767) return false;
        std::wstring path = input;
        for (size_t i = 0; i < path.size(); ++i)
        {
            auto& c = path[i];
            if (c == L'/') c = L'\\';
            if (c < 32 || c == L'"' || c == L'<' || c == L'>' || c == L'|' || c == L'?' || c == L'*')
                return false;
            if (c == L':' && i != 1) return false;
            if (c >= 0xd800 && c <= 0xdbff)
            {
                if (i + 1 >= path.size() || path[i + 1] < 0xdc00 || path[i + 1] > 0xdfff) return false;
                ++i;
            }
            else if (c >= 0xdc00 && c <= 0xdfff) return false;
        }
        if (path.back() == L'\\') return false;
        size_t start = 0;
        std::wstring prefix;
        size_t protectedComponents = 0;
        if (path.size() >= 3 && IsAsciiLetter(path[0]) && path[1] == L':' && path[2] == L'\\')
        {
            prefix = path.substr(0, 3);
            start = 3;
        }
        else if (path.size() > 2 && path[0] == L'\\' && path[1] == L'\\' && path[2] != L'\\')
        {
            prefix = L"\\\\";
            start = 2;
            protectedComponents = 2; // UNC server and share cannot be traversed.
        }
        else return false;

        std::vector<std::wstring> components;
        while (start <= path.size())
        {
            size_t end = path.find(L'\\', start);
            if (end == std::wstring::npos) end = path.size();
            auto part = path.substr(start, end - start);
            if (part == L"..")
            {
                if (components.size() <= protectedComponents) return false;
                components.pop_back();
            }
            else if (!part.empty() && part != L".")
            {
                if (part.back() == L'.' || part.back() == L' ' || part.find(L':') != std::wstring::npos)
                    return false;
                components.push_back(part);
            }
            else if (components.size() < protectedComponents) return false;
            if (end == path.size()) break;
            start = end + 1;
        }
        if (components.size() <= protectedComponents) return false;
        const auto& name = components.back();
        if (name.size() <= 4 || name[name.size() - 4] != L'.') return false;
        const wchar_t extension[] = L"vwx";
        for (size_t i = 0; i < 3; ++i)
        {
            wchar_t c = name[name.size() - 3 + i];
            if (c >= L'A' && c <= L'Z') c += L'a' - L'A';
            if (c != extension[i]) return false;
        }
        result = prefix;
        for (size_t i = 0; i < components.size(); ++i)
        {
            if (i) result += L'\\';
            result += components[i];
        }
        return true;
    }

    // ASCII JSON with explicit UTF-16 escapes preserves non-ASCII names,
    // surrogate pairs, quotes and controls without relying on locale codecs.
    inline std::string JsonString(const std::wstring& text)
    {
        const char hex[] = "0123456789abcdef";
        std::string result = "\"";
        for (wchar_t c : text)
        {
            if (c == L'"' || c == L'\\') { result += '\\'; result += static_cast<char>(c); }
            else if (c >= 32 && c <= 126) result += static_cast<char>(c);
            else
            {
                result += "\\u";
                for (int shift = 12; shift >= 0; shift -= 4) result += hex[(c >> shift) & 15];
            }
        }
        return result + '"';
    }

    inline std::string ErrorJson(std::uint32_t process, Status status)
    {
        return "{\"status\":\"error\",\"process_id\":" + std::to_string(process)
             + ",\"code\":" + std::to_string(static_cast<std::int32_t>(status)) + "}";
    }

    inline std::string SnapshotJson(std::uint32_t process, const Documents& documents)
    {
        std::string result = "{\"status\":\"ok\",\"process_id\":" + std::to_string(process)
                           + ",\"count\":" + std::to_string(documents.size()) + ",\"open_documents\":[";
        for (size_t i = 0; i < documents.size(); ++i)
        {
            const auto& doc = documents[i];
            if (i) result += ',';
            result += "{\"path\":" + JsonString(doc.path) + ",\"file_ref\":" + std::to_string(doc.fileRef)
                    + ",\"active\":" + (doc.active ? "true" : "false")
                    + ",\"in_memory_only\":" + (doc.inMemoryOnly ? "true" : "false") + "}";
        }
        return result + "]}";
    }

    template<class Host>
    Status CheckDocument(Host& host, const std::wstring& expected, Documents& documents)
    {
        if (!host.ReadDocuments(documents)) return Status::InventoryUnavailable;
        if (documents.size() != 1 || !documents[0].active || documents[0].inMemoryOnly)
            return Status::UnsafeDocuments;
        std::wstring actual;
        if (documents[0].fileRef < 0 || !NormalizeVwxPath(documents[0].path, actual))
            return Status::UnsafeDocuments;
        if (!host.PathsEqual(expected, actual)) return Status::PathMismatch;
        if (host.WorkingFile()) return Status::WorkingFile;
        if (!host.ActiveFileMatches(expected)) return Status::PathMismatch;
        return Status::Accepted;
    }

    template<class Host>
    Status Run(Host& host, const std::wstring& expectedPath, bool save)
    {
        try
        {
            if (!host.ContextReady()) return Status::InvalidContext;
            std::wstring expected;
            if (!NormalizeVwxPath(expectedPath, expected)) return Status::InvalidArguments;
            Documents before, current;
            auto checked = CheckDocument(host, expected, before);
            if (checked != Status::Accepted) return checked;
            // SDK calls may permit reentry; verify the complete set again,
            // including the open-file reference, immediately before acting.
            checked = CheckDocument(host, expected, current);
            if (checked != Status::Accepted || current[0].fileRef != before[0].fileRef)
                return Status::DocumentChanged;
            if (!host.ContextReady()) return Status::InvalidContext;
            // Quit saves again within this callback: the preceding menu job
            // may have dirtied the drawing after the controller's saved receipt.
            // This does not clear dirty flags or suppress subsequent prompts.
            if (!host.Save()) return Status::SaveFailed;
            if (!host.ContextReady()) return Status::InvalidContext;
            checked = CheckDocument(host, expected, current);
            if (checked != Status::Accepted || current[0].fileRef != before[0].fileRef)
                return Status::DocumentChanged;
            if (!host.ContextReady()) return Status::InvalidContext;
            if (!save)
            {
                host.Quit(); // Prompt-preserving normal quit; no automatic restart.
            }
            return Status::Accepted;
        }
        catch (...) { return Status::NativeException; }
    }
}
