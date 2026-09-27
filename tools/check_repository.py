"""Read-only publication hygiene for this Git checkout; standard library only."""
import argparse
import fnmatch
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
BANNED_SUFFIXES = frozenset({'.vlb', '.vwr', '.vst', '.dll', '.exe', '.lib', '.obj',
                            '.pch', '.pdb', '.ilk', '.exp', '.vwx', '.vwt', '.zip',
                            '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz', '.whl'})
CREDENTIAL_EXAMPLE = 'native/CredentialsVwxMcp.example.json'


def _git(root, *arguments, input=None, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(root), *arguments], input=input,
                            capture_output=True, check=False)
    if result.returncode not in allowed:
        # Git stderr can include private configuration. Keep diagnostics scoped.
        raise RuntimeError('Git command failed: ' + arguments[0])
    return result.stdout


def publishable_files(root):
    """Git paths only; deleted tracked files are deliberately omitted later."""
    raw = _git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
    return sorted({os.fsdecode(name) for name in raw.split(b'\0') if name})


def _reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _safe_path(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(part in ('..', '.') or ':' in part for part in parts):
        raise ValueError('Path escapes the repository')
    current = root
    for part in parts:
        current /= part
        try:
            if _reparse(current):
                raise ValueError('Symlinks/reparse points are not inspected')
        except FileNotFoundError:
            break
    return root.joinpath(*parts)


def _ignored_directories(root, relative_paths):
    if not relative_paths:
        return set()
    payload = b''.join(os.fsencode(name + '/') + b'\0' for name in relative_paths)
    raw = _git(root, 'check-ignore', '--stdin', '-z', input=payload, allowed=(0, 1))
    return {os.fsdecode(name).rstrip('/') for name in raw.split(b'\0') if name}


def _empty_directories(root):
    pending = [root]
    while pending:
        parent = pending.pop()
        entries = list(os.scandir(parent))
        if parent != root and not entries:
            yield parent.relative_to(root).as_posix()
        children = []
        for entry in entries:
            if entry.name == '.git':
                continue
            path = Path(entry.path)
            if not _reparse(path) and entry.is_dir(follow_symlinks=False):
                children.append(path.relative_to(root).as_posix())
        ignored = _ignored_directories(root, children)
        pending.extend(root / name for name in children if name not in ignored)


def _markdown_links(source):
    fence = None
    for number, line in enumerate(source.splitlines(), 1):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        if line.startswith(('    ', '\t')):
            continue
        line = re.sub(r'(`+).*?\1', '', line)
        # Normal inline links/images and reference-link definitions. Angle
        # brackets permit spaces; optional link titles are not part of paths.
        matches = re.findall(r'\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+["\'][^)]*)?\s*\)', line)
        definition = re.match(r'^ {0,3}\[[^]]+\]:\s*(<[^>]+>|\S+)', line)
        if definition:
            matches.append(definition[1])
        for target in matches:
            yield number, target.strip('<>')


def check_repository(root=ROOT):
    root = Path(root).resolve(strict=True)
    errors = []
    files = publishable_files(root)
    present = {}
    for relative in files:
        try:
            path = _safe_path(root, relative)
            if not path.exists():
                continue
            if not path.is_file():
                errors.append(f'{relative}: expected a regular publication file')
                continue
            present[relative] = path
            if path.suffix.lower() in BANNED_SUFFIXES:
                errors.append(f'{relative}: generated binary, drawing or archive must not be published')
            if fnmatch.fnmatchcase(path.name.lower(), 'credentials*.json') and relative != CREDENTIAL_EXAMPLE:
                errors.append(f'{relative}: private credential/request JSON must be ignored')
            data = path.read_bytes()
            try:
                text = data.decode('utf-8-sig')
                blank = not text.strip()
            except UnicodeDecodeError:
                text, blank = None, not data.strip()
            if blank:
                errors.append(f'{relative}: empty or whitespace-only file')
        except (OSError, ValueError) as error:
            errors.append(f'{relative}: cannot safely inspect file ({type(error).__name__})')
    for relative, path in present.items():
        if path.suffix.lower() != '.md':
            continue
        try:
            source = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            errors.append(f'{relative}: cannot read Markdown as UTF-8')
            continue
        for number, link in _markdown_links(source):
            try:
                parsed = urlsplit(link)
            except ValueError:
                errors.append(f'{relative}:{number}: malformed Markdown link target')
                continue
            if len(parsed.scheme) == 1 and parsed.scheme.isalpha():
                errors.append(f'{relative}:{number}: nonportable local Markdown link')
                continue
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            decoded = unquote(parsed.path)
            if decoded.startswith('/') or '\\' in decoded:
                errors.append(f'{relative}:{number}: nonportable local Markdown link')
                continue
            # Normalize '..' lexically, then reject any target outside root.
            normalized = Path(os.path.abspath(path.parent / decoded))
            try:
                target_relative = normalized.relative_to(root).as_posix()
                target = root if normalized == root else _safe_path(root, target_relative)
                if not target.exists():
                    errors.append(f'{relative}:{number}: missing Markdown target {target_relative}')
                elif target.is_file() and target_relative not in present:
                    errors.append(f'{relative}:{number}: Markdown target is not publishable: {target_relative}')
                elif target.is_dir() and target != root and not any(name.startswith(target_relative + '/') for name in present):
                    errors.append(f'{relative}:{number}: Markdown directory is not publishable: {target_relative}')
            except (OSError, ValueError):
                errors.append(f'{relative}:{number}: unsafe or outside-repository Markdown target')
    try:
        errors.extend(f'{name}/: empty nonignored directory' for name in _empty_directories(root))
    except OSError:
        errors.append('Cannot safely enumerate repository directories')
    return sorted(set(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    arguments = parser.parse_args()
    try:
        errors = check_repository(arguments.root)
    except (OSError, RuntimeError) as error:
        print('Repository check could not complete: ' + str(error))
        return 1
    for error in errors:
        print(error)
    if not errors:
        print('Repository publication hygiene passed.')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
