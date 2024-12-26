#!/bin/bash
find . -type f -name '*.py' -or -name "Pipfile*" | entr -r sh -c 'make dev'
