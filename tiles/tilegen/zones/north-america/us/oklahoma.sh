#!/bin/sh

# 
# Tiles for Oklahoma
# north-america/us/oklahoma 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/oklahoma.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-oklahoma/ --zooms 11 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/oklahoma.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-oklahoma/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/oklahoma.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-oklahoma/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/oklahoma.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-oklahoma/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/

# cleanup
echo "[Cleanup] This may take a while so hold tight."
cd ../../../output/north-america-us-oklahoma/
find . -empty -type d -delete

# packup
echo "[Packing] Please wait."
7z a north-america-us-oklahoma.7z .

# done
echo "[Done] Ready for upload."
