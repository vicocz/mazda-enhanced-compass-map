#!/bin/sh

# 
# Tiles for Nebraska
# north-america/us/nebraska 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/nebraska.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nebraska/ --zooms 11 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/nebraska.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nebraska/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/nebraska.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nebraska/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/nebraska.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-nebraska/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/

# cleanup
echo "[Cleanup] This may take a while so hold tight."
cd ../../../output/north-america-us-nebraska/
find . -empty -type d -delete

# packup
echo "[Packing] Please wait."
7z a north-america-us-nebraska.7z .

# done
echo "[Done] Ready for upload."
