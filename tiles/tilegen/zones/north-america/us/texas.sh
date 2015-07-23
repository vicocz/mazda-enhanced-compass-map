#!/bin/sh

# 
# Tiles for Texas
# north-america/us/texas 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/texas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-texas/ --zooms 0 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/texas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-texas/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/texas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-texas/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/texas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-texas/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/

