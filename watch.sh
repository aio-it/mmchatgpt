#!/bin/bash
find . -type f -name '*.py' -or -name "Pipfile*" | entr -r make dev
