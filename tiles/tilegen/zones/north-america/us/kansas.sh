#!/bin/sh

# 
# Tiles for Kansas
# north-america/us/kansas 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/kansas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-kansas/ --zooms 11 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/kansas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-kansas/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/kansas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-kansas/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/kansas.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-kansas/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/

# cleanup
echo "[Cleanup] This may take a while so hold tight."
cd ../../../output/north-america-us-kansas/
find . -empty -type d -delete

# packup
echo "[Packing] Please wait."
7z a north-america-us-kansas.7z .

# done
echo "[Done] Ready for upload."
