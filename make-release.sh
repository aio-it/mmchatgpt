#!/bin/bash
# get latest tag
tag=$(git describe --tags `git rev-list --tags --max-count=1`)

# check if current commit is already tagged if so tell the user and exit
if [ $(git describe --tags) == $tag ]; then
    echo "Current commit is already tagged with $tag"
    exit 1
fi

# get if we want to make a major, minor or patch release
release=$1
#remove v from tag
tag=$(echo $tag | cut -c 2-)
# update the new_tag to the new version
# tags are in the format of vx.y.z
# x = major, y = minor, z = patch
if [ "$release" == "major" ]; then
    new_tag=$(echo $tag | awk -F. '{print "v"$1+1".0.0"}')
elif [ "$release" == "minor" ]; then
    new_tag=$(echo $tag | awk -F. '{print "v"$1"."$2+1".0"}')
elif [ "$release" == "patch" ]; then
    new_tag=$(echo $tag | awk -F. '{print "v"$1"."$2"."$3+1}')
else
    echo "Please specify the type of release: major, minor or patch"
    exit 1
fi
echo "Creating new tag: $new_tag"
git push
git tag $new_tag
git push --tags