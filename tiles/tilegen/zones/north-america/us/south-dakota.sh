#!/bin/sh

# 
# Tiles for South Dakota
# north-america/us/south-dakota 
#

cd ../../../base

./polytiles.py -p ../poly/north-america/us/south-dakota.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-south-dakota/ --zooms 11 11 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/south-dakota.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-south-dakota/ --zooms 13 13 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/south-dakota.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-south-dakota/ --zooms 15 15 --delete-empty --custom-fonts ../../../fonts/
./polytiles.py -p ../poly/north-america/us/south-dakota.poly -s ../../tilestyles/mazda/mazda.xml -t ../../../output/north-america-us-south-dakota/ --zooms 17 17 --delete-empty --custom-fonts ../../../fonts/

# cleanup
echo "[Cleanup] This may take a while so hold tight."
cd ../../../output/north-america-us-south-dakota/
find . -empty -type d -delete

# packup
echo "[Packing] Please wait."
7z a north-america-us-south-dakota.7z .

# done
echo "[Done] Ready for upload."
