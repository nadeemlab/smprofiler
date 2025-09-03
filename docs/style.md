# Code styling

## Python

New additions to the library should be fully type hinted and follow PEP 8 guidelines. To this end, please use the following linters in your development environment:
* Style: pylint (recommended for its additional features) or pycodestyle
    * autopep8 is recommended for speeding up style compliance but not required
* Typing: mypy or pylance/pyright
* Spell-checking: any code-friendly option

## IDEs

We recommend developing in VS Code or PyCharm, but any environment that supports our recommended linters should be sufficient.

The following line may be used to do whole-package linting:

```sh
pylint smprofiler/ --output-format=colorized --rc-file .pylintrc
```

Linting is also added as a Github action, triggered on every merge into main and on every pull request opening, editing, repening, or synchronize events.
