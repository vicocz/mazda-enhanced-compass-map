#!/bin/sh

# 
# Tiles for Nevada
# north-america/us/nevada 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/nevada.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nevada/ --zooms 0 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/nevada.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nevada/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/nevada.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nevada/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/nevada.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nevada/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/
