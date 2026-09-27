// Exercise the production publisher against real Windows file-sharing rules.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "../native/Source/Bridge/AtomicStatusFile.h"

#include <atomic>
#include <chrono>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;
using VwxBridge::WriteAtomicStatusFile;

void Require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}

struct Handle
{
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE handle) : value(handle) {}
    ~Handle() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};

std::string ReadHandle(HANDLE handle)
{
    LARGE_INTEGER zero{};
    Require(SetFilePointerEx(handle, zero, nullptr, FILE_BEGIN), "Cannot rewind opened status file");
    std::string result;
    char buffer[8192];
    DWORD count = 0;
    do {
        Require(ReadFile(handle, buffer, sizeof(buffer), &count, nullptr), "Cannot read opened status file");
        result.append(buffer, count);
        Require(result.size() <= 1024 * 1024, "Unexpected status-file size");
    } while (count != 0);
    return result;
}

std::string ReadPath(const fs::path& path)
{
    Handle file(CreateFileW(path.c_str(), GENERIC_READ,
                           FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    Require(file.value != INVALID_HANDLE_VALUE, "Status file disappeared or cannot be opened");
    return ReadHandle(file.value);
}

void OnlyExpectedFile(const fs::path& directory, const fs::path& expected)
{
    size_t count = 0;
    for (const auto& entry : fs::directory_iterator(directory)) {
        Require(entry.path() == expected, "Atomic publication leaked a temporary file");
        ++count;
    }
    Require(count == 1, "Expected exactly one published file");
}

void BasicAndUnicode(const fs::path& base)
{
    const auto directory = base / L"unicode-\u6D4B\u8BD5-\u00E9";
    fs::create_directory(directory);
    const auto path = directory / L"\u72B6\u6001-\u00E9.json";
    const std::string old = "{\"schema\":1,\"value\":\"first\"}\n";
    Require(WriteAtomicStatusFile(path.wstring(), old), "First publication failed");
    Require(ReadPath(path) == old, "First publication changed payload");
    OnlyExpectedFile(directory, path);

    // Embedded NULs and a much larger replacement independently check byte
    // counts; the helper accepts a string, not a null-terminated text pointer.
    std::string large(131071, 'L');
    large[17] = '\0';
    large.back() = '\n';
    Require(WriteAtomicStatusFile(path.wstring(), large), "Large replacement failed");
    Require(ReadPath(path) == large, "Large replacement was incomplete");
    Require(WriteAtomicStatusFile(path.wstring(), "small\n"), "Short replacement failed");
    Require(ReadPath(path) == "small\n", "Short replacement retained old trailing bytes");
    Require(!WriteAtomicStatusFile(path.wstring(), ""), "Empty diagnostics incorrectly published");
    Require(ReadPath(path) == "small\n", "Rejected empty diagnostics damaged the prior value");
    Require(!WriteAtomicStatusFile(L"", "some content"), "An empty path was accepted");
    OnlyExpectedFile(directory, path);
    std::cout << "unicode_and_exact_bytes passed\n";
}

void LockedDestinationPreservesOld(const fs::path& base)
{
    const auto directory = base / L"locked";
    fs::create_directory(directory);
    const auto path = directory / L"native.scheduler.json";
    const std::string old = "{\"generation\":11,\"complete\":true}\n";
    Require(WriteAtomicStatusFile(path.wstring(), old), "Locked-test setup failed");
    {
        // This permits reads but denies replacement/deletion. A writer that
        // truncates the destination first would destroy the independent oracle.
        Handle held(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ,
                                nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        Require(held.value != INVALID_HANDLE_VALUE, "Cannot hold destination without delete sharing");
        for (const auto& attempted : {std::string("new\n"), std::string(65537, 'X')}) {
            Require(!WriteAtomicStatusFile(path.wstring(), attempted), "Locked publication incorrectly claimed success");
            Require(ReadHandle(held.value) == old, "Failed publication damaged the opened old file");
            Require(ReadPath(path) == old, "Failed publication changed the destination path's old payload");
            OnlyExpectedFile(directory, path);
        }
    }
    Require(WriteAtomicStatusFile(path.wstring(), "after-release\n"), "Publication did not work after releasing test lock");
    Require(ReadPath(path) == "after-release\n", "Post-lock publication incomplete");
    OnlyExpectedFile(directory, path);
    std::cout << "locked_failure_preserves_old passed\n";
}

void OldReaderSurvivesReplacement(const fs::path& base)
{
    const auto directory = base / L"old-reader";
    fs::create_directory(directory);
    const auto path = directory / L"native.alive";
    const std::string old(4001, 'O'), next(701, 'N');
    Require(WriteAtomicStatusFile(path.wstring(), old), "Old-reader setup failed");
    {
        Handle held(CreateFileW(path.c_str(), GENERIC_READ,
                                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        Require(held.value != INVALID_HANDLE_VALUE, "Cannot hold old generation for reading");
        const bool published = WriteAtomicStatusFile(path.wstring(), next);
        Require(ReadHandle(held.value) == old, "Existing reader saw a truncated/reused old generation");
        Require(ReadPath(path) == (published ? next : old), "Publication result disagrees with complete path contents");
    }
    Require(WriteAtomicStatusFile(path.wstring(), next), "Post-reader publication failed");
    Require(ReadPath(path) == next, "Post-reader generation is incomplete");
    OnlyExpectedFile(directory, path);
    std::cout << "old_handle_generation passed\n";
}

void ConcurrentReaders(const fs::path& base)
{
    const auto directory = base / L"concurrent";
    fs::create_directory(directory);
    const auto path = directory / L"native.scheduler.json";
    const std::vector<std::string> payloads = {
        "{\"generation\":0,\"value\":\"" + std::string(29, 'A') + "\"}\n",
        "{\"generation\":1,\"value\":\"" + std::string(4097, 'B') + "\"}\n",
        "{\"generation\":2,\"value\":\"" + std::string(131071, 'C') + "\"}\n",
        "{\"generation\":3,\"value\":\"" + std::string(1003, 'D') + "\"}\n"
    };
    Require(WriteAtomicStatusFile(path.wstring(), payloads[0]), "Concurrency setup failed");
    std::atomic<bool> stop{false};
    std::atomic<unsigned> reads{0}, busyOpens{0}, seen{0};
    std::mutex errorsMutex;
    std::string failure;
    auto fail = [&](const char* message) {
        std::lock_guard<std::mutex> guard(errorsMutex);
        if (failure.empty()) failure = message;
        stop.store(true);
    };
    auto reader = [&] {
        try {
            while (!stop.load()) {
                Handle handle(CreateFileW(path.c_str(), GENERIC_READ,
                                          FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                          nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
                if (handle.value == INVALID_HANDLE_VALUE) {
                    const DWORD error = GetLastError();
                    // Windows may deny an open during rename/delete sharing
                    // arbitration. That is not a partial successful read. The
                    // published path must never disappear between generations.
                    if (error != ERROR_SHARING_VIOLATION && error != ERROR_ACCESS_DENIED)
                        throw std::runtime_error("Concurrent open lost the published destination");
                    ++busyOpens;
                    std::this_thread::yield();
                    continue;
                }
                const auto actual = ReadHandle(handle.value);
                bool complete = false;
                for (unsigned index = 0; index < payloads.size(); ++index) {
                    if (actual == payloads[index]) {
                        complete = true;
                        seen.fetch_or(1u << index);
                    }
                }
                if (!complete) throw std::runtime_error("Reader observed truncated, empty, mixed or unknown payload");
                ++reads;
            }
        } catch (const std::exception& error) { fail(error.what()); }
    };
    std::thread first(reader), second(reader);
    unsigned publishedCount = 0, rejectedCount = 0;
    std::string lastPublished = payloads[0];
    try {
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (reads.load() < 25 && !stop.load() && std::chrono::steady_clock::now() < deadline)
            std::this_thread::yield();
        Require(reads.load() >= 25, "Reader threads did not start");
        for (unsigned i = 1; i <= 160 && !stop.load(); ++i) {
            const auto& next = payloads[i % payloads.size()];
            if (WriteAtomicStatusFile(path.wstring(), next)) {
                lastPublished = next;
                ++publishedCount;
            } else {
                ++rejectedCount;
                Require(ReadPath(path) == lastPublished, "Rejected concurrent publication changed the old generation");
            }
            std::this_thread::yield();
        }
    } catch (const std::exception& error) { fail(error.what()); }
    stop.store(true);
    first.join();
    second.join();
    Require(failure.empty(), failure.c_str());
    Require(reads.load() >= 25, "No meaningful concurrent read sample");
    Require(publishedCount > 0 && (seen.load() & (seen.load() - 1)) != 0,
            "Concurrency test did not observe multiple complete published generations");
    Require(ReadPath(path) == lastPublished, "Final generation differs from writer's last successful publication");
    OnlyExpectedFile(directory, path);
    std::cout << "concurrent_complete_generations passed reads=" << reads.load()
              << " publications=" << publishedCount << " rejected_publications=" << rejectedCount
              << " transient_busy_opens=" << busyOpens.load() << '\n';
}

void InvalidParent(const fs::path& base)
{
    const auto directory = base / L"invalid-parent";
    fs::create_directory(directory);
    const auto existing = directory / L"keep.dat";
    Require(WriteAtomicStatusFile(existing.wstring(), "preserve this file"), "Failure-test setup failed");
    Require(!WriteAtomicStatusFile((existing / L"child.json").wstring(), "rejected"),
            "A file was incorrectly treated as a parent directory");
    Require(ReadPath(existing) == "preserve this file", "Failed write damaged existing parent file");
    Require(!WriteAtomicStatusFile((directory / L"missing" / L"child.json").wstring(), "rejected"),
            "Unexpectedly created a missing parent directory");
    OnlyExpectedFile(directory, existing);
    std::cout << "invalid_parent_preserves_existing passed\n";
}

int wmain(int argc, wchar_t** argv)
{
    try {
        Require(argc == 2, "Pass the disposable test directory");
        const fs::path base(argv[1]);
        Require(fs::is_directory(base) && fs::is_empty(base), "Test directory must exist and be empty");
        BasicAndUnicode(base);
        LockedDestinationPreservesOld(base);
        OldReaderSurvivesReplacement(base);
        ConcurrentReaders(base);
        InvalidParent(base);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "atomic status test failed: " << error.what() << '\n';
        return 1;
    }
}
