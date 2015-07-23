#!/bin/sh

# 
# Tiles for Ohio
# north-america/us/ohio 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/ohio.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-ohio/ --zooms 0 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/ohio.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-ohio/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/ohio.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-ohio/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/ohio.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-ohio/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/
