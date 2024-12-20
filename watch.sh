#!/bin/bash
find plugins/ -type f | entr -r make dev
