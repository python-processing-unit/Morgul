import importlib.metadata as metadata

packages = [
    'argon2-cffi', 'argon2-cffi-bindings', 'cffi', 'pycparser',
    'markdown-it-py', 'mdurl', 'mdit-py-plugins', 'pynacl',
    'pyside6-essentials', 'shiboken6', 'typing-extensions', 'zstandard',
    'zxcvbn', 'pytest', 'colorama', 'iniconfig', 'packaging',
    'pluggy', 'pygments', 'ruff', 'ty'
]

for pkg in packages:
    try:
        dist = metadata.distribution(pkg)
        meta = dist.metadata
        version = meta.get('Version', 'UNKNOWN')
        license = meta.get('License', 'UNKNOWN')
        author = meta.get('Author', 'UNKNOWN')
        home_page = meta.get('Home-page', 'UNKNOWN')
        summary = meta.get('Summary', 'UNKNOWN')
        classifiers = meta.get_all('Classifier', []) or []
        license_classifiers = [c for c in classifiers if 'License' in c]

        print(f'=== {pkg} {version} ===')
        print(f'License: {license}')
        print(f'Author: {author}')
        print(f'Home-page: {home_page}')
        print(f'Summary: {summary}')
        for lc in license_classifiers:
            print(f'  Classifier: {lc}')
        print()
    except Exception as e:
        print(f'{pkg}|ERROR: {e}')
