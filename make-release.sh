#!/bin/bash
# get latest tag
tag=$(git describe --tags `git rev-list --tags --max-count=1`)

# check if current commit is already tagged if so tell the user and exit
if [ $(git describe --tags) == $tag ]; then
    echo "Current commit is already tagged with $tag"
    echo "Did you forget to commit your changes?"
    exit 1
fi
# commit the requirements.txt file
git commit -vm "updated requirements.txt" requirements.txt 2> /dev/null

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
# writing the new tag to the version file
echo $new_tag > version
# commit the version file
git commit -am "Bump version to $new_tag"
echo "Creating new tag: $new_tag"
git push
git tag $new_tag
git push --tags