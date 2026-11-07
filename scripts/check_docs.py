"""Offline checks for maintained Markdown links, anchors and source references."""
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('README.md', 'CI.md', 'docs/README.md', 'docs/ARCHITECTURE.md',
            'docs/CONFIGURATION.md', 'docs/WORKFLOWS.md', 'docs/API.md',
            'docs/DATA_CONTRACTS.md', 'docs/DEVELOPMENT.md', 'docs/OPERATIONS.md')


def prose(text):
    return re.sub(r'^```.*?^```[^\n]*', '', text, flags=re.M | re.S)


def anchors(text):
    result, counts = set(), {}
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', prose(text), re.M):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        number = counts.get(slug, 0)
        counts[slug] = number + 1
        result.add(slug + (f'-{number}' if number else ''))
    return result


def check(root=ROOT):
    root = Path(root).resolve()
    errors = [f'Missing canonical guide: {p}' for p in REQUIRED if not (root / p).is_file()]
    files = [root / 'README.md', root / 'CI.md', *sorted((root / 'docs').glob('*.md'))]
    for path in files:
        if not path.is_file():
            continue
        text = prose(path.read_text())
        for href in re.findall(r'\]\(([^\s)]+)\)', text):
            parts = urlsplit(href)
            if parts.scheme or parts.netloc:
                continue  # External URLs are deliberately not requested.
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            if not target.is_relative_to(root) or not target.is_file():
                errors.append(f'{path.relative_to(root)}: missing/outside link {href}')
            elif parts.fragment and target.suffix == '.md' and unquote(parts.fragment) not in anchors(target.read_text()):
                errors.append(f'{path.relative_to(root)}: missing anchor {href}')
        if path.name.startswith('WORKSPACE_'):
            continue  # Dated evidence may refer to native-only historical paths.
        for ref in re.findall(r'`((?:apps|scripts|compute|data|datasources|shared)/[^`\s]+)`', text):
            if not any(c in ref for c in '*<>') and not (root / ref.rstrip('/')).exists():
                errors.append(f'{path.relative_to(root)}: missing source reference {ref}')
    return errors


def main():
    errors = check()
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(1)
    print('Documentation links, anchors, source references and required guides pass (offline).')


if __name__ == '__main__':
    main()
