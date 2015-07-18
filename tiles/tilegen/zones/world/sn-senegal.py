#!/usr/bin/env python

# Tooling Template for Tile Generation
# DO NOT MODIFY 


from math import pi,cos,sin,log,exp,atan
from subprocess import call
import sys, os
from Queue import Queue
import threading
import mapnik

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi

# Default number of rendering threads to spawn, should be roughly equal to number of CPU cores available
NUM_THREADS = 6


def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a

class GoogleProjection:
    def __init__(self,levels=18):
        self.Bc = []
        self.Cc = []
        self.zc = []
        self.Ac = []
        c = 256
        for d in range(0,levels):
            e = c/2;
            self.Bc.append(c/360.0)
            self.Cc.append(c/(2 * pi))
            self.zc.append((e,e))
            self.Ac.append(c)
            c *= 2
                
    def fromLLtoPixel(self,ll,zoom):
         d = self.zc[zoom]
         e = round(d[0] + ll[0] * self.Bc[zoom])
         f = minmax(sin(DEG_TO_RAD * ll[1]),-0.9999,0.9999)
         g = round(d[1] + 0.5*log((1+f)/(1-f))*-self.Cc[zoom])
         return (e,g)
     
    def fromPixelToLL(self,px,zoom):
         e = self.zc[zoom]
         f = (px[0] - e[0])/self.Bc[zoom]
         g = (px[1] - e[1])/-self.Cc[zoom]
         h = RAD_TO_DEG * ( 2 * atan(exp(g)) - 0.5 * pi)
         return (f,h)



class RenderThread:
    def __init__(self, tile_dir, mapfile, q, printLock, maxZoom):
        self.tile_dir = tile_dir
        self.q = q
        self.m = mapnik.Map(256, 256)
        self.printLock = printLock
        # Load style XML
        mapnik.load_map(self.m, mapfile, True)
        # Obtain <Map> projection
        self.prj = mapnik.Projection(self.m.srs)
        # Projects between tile pixel co-ordinates and LatLong (EPSG:4326)
        self.tileproj = GoogleProjection(maxZoom+1)


    def render_tile(self, tile_uri, x, y, z):

        # Calculate pixel positions of bottom-left & top-right
        p0 = (x * 256, (y + 1) * 256)
        p1 = ((x + 1) * 256, y * 256)

        # Convert to LatLong (EPSG:4326)
        l0 = self.tileproj.fromPixelToLL(p0, z);
        l1 = self.tileproj.fromPixelToLL(p1, z);

        # Convert to map projection (e.g. mercator co-ords EPSG:900913)
        c0 = self.prj.forward(mapnik.Coord(l0[0],l0[1]))
        c1 = self.prj.forward(mapnik.Coord(l1[0],l1[1]))

        # Bounding box for the tile
        if hasattr(mapnik,'mapnik_version') and mapnik.mapnik_version() >= 800:
            bbox = mapnik.Box2d(c0.x,c0.y, c1.x,c1.y)
        else:
            bbox = mapnik.Envelope(c0.x,c0.y, c1.x,c1.y)
        render_size = 256
        self.m.resize(render_size, render_size)
        self.m.zoom_to_box(bbox)
        if(self.m.buffer_size < 128):
            self.m.buffer_size = 128

        # Render image with default Agg renderer
        im = mapnik.Image(render_size, render_size)
        mapnik.render(self.m, im)
        im.save(tile_uri, 'png256')


    def loop(self):
        while True:
            #Fetch a tile from the queue and render it
            r = self.q.get()
            if (r == None):
                self.q.task_done()
                break
            else:
                (name, tile_uri, x, y, z) = r

            exists= ""
            if os.path.isfile(tile_uri):
                exists= "exists"
            else:
                self.render_tile(tile_uri, x, y, z)
            bytes=os.stat(tile_uri)[6]
            empty= ''

            if bytes == 103:
                empty = " Empty Tile "
                os.remove(tile_uri)

            self.printLock.acquire()
            print name, ":", z, x, y, exists, empty
            self.printLock.release()
            self.q.task_done()



def render_tiles(bbox, mapfile, tile_dir, minZoom=1,maxZoom=18, name="unknown", num_threads=NUM_THREADS, tms_scheme=False):
    print "render_tiles(",bbox, mapfile, tile_dir, minZoom,maxZoom, name,")"

    tile_dir = tile_dir + name + "/";

    # Launch rendering threads
    queue = Queue(32)
    printLock = threading.Lock()
    renderers = {}
    for i in range(num_threads):
        renderer = RenderThread(tile_dir, mapfile, queue, printLock, maxZoom)
        render_thread = threading.Thread(target=renderer.loop)
        render_thread.start()
        #print "Started render thread %s" % render_thread.getName()
        renderers[i] = render_thread

    if not os.path.exists(tile_dir):
         os.makedirs(tile_dir)

    gprj = GoogleProjection(maxZoom+1) 

    ll0 = (bbox[0],bbox[3])
    ll1 = (bbox[2],bbox[1])

    for z in range(minZoom,maxZoom + 1):
        px0 = gprj.fromLLtoPixel(ll0,z)
        px1 = gprj.fromLLtoPixel(ll1,z)

        # check if we have directories in place
        zoom = "%s" % z
        if not os.path.isdir(tile_dir + zoom):
            os.mkdir(tile_dir + zoom)
        for x in range(int(px0[0]/256.0),int(px1[0]/256.0)+1):
            # Validate x co-ordinate
            if (x < 0) or (x >= 2**z):
                continue
            # check if we have directories in place
            str_x = "%s" % x
            if not os.path.isdir(tile_dir + zoom + '/' + str_x):
                os.mkdir(tile_dir + zoom + '/' + str_x)
            for y in range(int(px0[1]/256.0),int(px1[1]/256.0)+1):
                # Validate x co-ordinate
                if (y < 0) or (y >= 2**z):
                    continue
                # flip y to match OSGEO TMS spec
                if tms_scheme:
                    str_y = "%s" % ((2**z-1) - y)
                else:
                    str_y = "%s" % y
                tile_uri = tile_dir + zoom + '/' + str_x + '/' + str_y + '.png'
                # Submit tile to be rendered into the queue
                t = (name, tile_uri, x, y, z)
                try:
                    queue.put(t)
                except KeyboardInterrupt:
                    raise SystemExit("Ctrl-c detected, exiting...")

    # Signal render threads to exit by sending empty request to queue
    for i in range(num_threads):
        queue.put(None)
    # wait for pending rendering jobs to complete
    queue.join()
    for i in range(num_threads):
        renderers[i].join()




if __name__ == "__main__":
    home = os.environ['HOME']
    try:
        mapfile = "../tilestyles/mazda/mazda.xml"
    except KeyError:
        print("[MapFile] Not found")
        sys.exit(1)
    try:
        # ./tilegen/zones/[zone]/[region]
        tile_dir = "../../../output/"
    except KeyError:
        print("[OutputDir] No output directory found")
        sys.exit(1)

    if not tile_dir.endswith('/'):
        tile_dir = tile_dir + '/'


    # ------------------------------------------------------------------------
    # Tile Render Data
    # Zone: world
    # Region: SN
    # Region Name: Senegal

	render_tiles((-12.34528,12.30139,-16.72056,12.32305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.72056,12.32305,-16.67781,12.33458), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.67781,12.33458,-16.72056,12.32305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.57278,12.35916,-16.46389,12.36111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.46389,12.36111,-12.57278,12.35916), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.43639,12.38277,-11.84167,12.38639), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.84167,12.38639,-12.43639,12.38277), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.96889,12.39139,-11.84167,12.38639), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.49694,12.39667,-11.96889,12.39139), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.37333,12.40464,-12.09889,12.41028), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.09889,12.41028,-16.78972,12.41583), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.78972,12.41583,-12.09889,12.41028), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.90833,12.42889,-15.68556,12.43), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.68556,12.43,-11.90833,12.42889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.48639,12.43666,-12.63333,12.4375), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.63333,12.4375,-11.48639,12.43666), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.20916,12.46083,-11.35833,12.46749), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.35833,12.46749,-13.03778,12.47305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.03778,12.47305,-12.95528,12.47639), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.95528,12.47639,-13.03778,12.47305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.84139,12.48,-12.95528,12.47639), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.79945,12.48917,-12.84139,12.48), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.06889,12.525,-15.62722,12.53111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.62722,12.53111,-16.76667,12.53277), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.76667,12.53277,-15.62722,12.53111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.93167,12.54111,-12.89167,12.54305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.89167,12.54305,-16.37417,12.54444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.37417,12.54444,-12.89167,12.54305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.45194,12.55055,-15.81778,12.55111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.81778,12.55111,-11.45194,12.55055), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.65639,12.55611,-15.40722,12.55694), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.40722,12.55694,-15.65639,12.55611), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.77444,12.57444,-16.41972,12.57555), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.41972,12.57555,-16.77444,12.57444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.72278,12.57889,-16.41972,12.57555), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.52834,12.58583,-15.76722,12.58917), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.76722,12.58917,-13.04167,12.59), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.04167,12.59,-15.76722,12.58917), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.49528,12.59555,-16.34111,12.59778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.34111,12.59778,-15.91833,12.59861), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.91833,12.59861,-16.34111,12.59778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.67472,12.60833,-15.91833,12.59861), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.46889,12.61944,-11.4225,12.62361), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.4225,12.62361,-16.51306,12.62444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.51306,12.62444,-11.4225,12.62361), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.55611,12.62778,-16.015,12.63083), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.015,12.63083,-16.07972,12.63166), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.07972,12.63166,-16.015,12.63083), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.58083,12.6325,-16.07972,12.63166), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.64528,12.63416,-15.50806,12.63472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.50806,12.63472,-16.64528,12.63416), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.06139,12.63972,-15.50806,12.63472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.62611,12.65583,-15.52695,12.66222), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.52695,12.66222,-13.71255,12.66603), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.71255,12.66603,-15.52695,12.66222), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.92833,12.67666,-15.21833,12.68472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.21833,12.68472,-16.57084,12.68806), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.57084,12.68806,-15.21833,12.68472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.63917,12.7,-15.54945,12.70472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.54945,12.70472,-16.63917,12.7), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.79361,12.71222,-11.42861,12.71389), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.42861,12.71389,-16.79361,12.71222), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.65028,12.71889,-11.42861,12.71389), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.38333,12.72666,-16.02472,12.72778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.02472,12.72778,-11.38333,12.72666), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.59333,12.745,-16.02472,12.72778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.55556,12.76861,-15.52806,12.78361), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.52806,12.78361,-16.59806,12.79166), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.59806,12.79166,-15.395,12.79666), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.395,12.79666,-16.59806,12.79166), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.45667,12.82861,-15.39,12.83194), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.39,12.83194,-15.45667,12.82861), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.41222,12.91611,-11.36806,12.92889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.36806,12.92889,-16.75723,12.93389), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.75723,12.93389,-11.36806,12.92889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.42,12.95944,-16.75723,12.93389), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.37806,12.98805,-11.42,12.95944), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.77482,13.03709,-11.43472,13.07611), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.43472,13.07611,-16.77482,13.03709), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.52778,13.13778,-15.80944,13.16), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.80944,13.16,-16.70055,13.16139), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.70055,13.16139,-15.80944,13.16), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.2975,13.24111,-14.37833,13.245), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.37833,13.245,-14.2975,13.24111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.79833,13.31278,-13.84972,13.33361), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.84972,13.33361,-14.64778,13.34444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.64778,13.34444,-15.80889,13.34889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.80889,13.34889,-14.64778,13.34444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.5675,13.36111,-14.57361,13.36305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.57361,13.36305,-11.59778,13.36472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.59778,13.36472,-14.57361,13.36305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.36,13.36722,-14.72806,13.36889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.72806,13.36889,-15.36,13.36722), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.75694,13.37305,-11.88528,13.375), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.88528,13.375,-11.75694,13.37305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.25945,13.38556,-11.88528,13.375), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.50528,13.39833,-13.79861,13.40027), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.79861,13.40027,-15.50528,13.39833), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.71972,13.41278,-13.79861,13.40027), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.21278,13.42972,-11.71972,13.41278), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.80833,13.45305,-14.85056,13.45388), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.85056,13.45388,-13.80833,13.45305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.33778,13.45388,-13.80833,13.45305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.86806,13.4575,-14.85056,13.45388), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.95444,13.4725,-11.86806,13.4575), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.86906,13.50849,-14.43528,13.50972), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.43528,13.50972,-13.86906,13.50849), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.19695,13.535,-14.43528,13.50972), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.91417,13.56667,-13.98778,13.5825), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.98778,13.5825,-15.48889,13.58944), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.48889,13.58944,-16.56927,13.59005), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.56927,13.59005,-15.48889,13.58944), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.11139,13.59583,-16.56927,13.59005), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.71889,13.61194,-15.11139,13.59583), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.51195,13.63444,-16.57333,13.64611), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.57333,13.64611,-16.60973,13.64778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.60973,13.64778,-16.57333,13.64611), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.79195,13.65333,-16.60973,13.64778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.05445,13.66055,-14.64917,13.66222), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.64917,13.66222,-12.05445,13.66055), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.59917,13.67027,-14.64917,13.66222), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.50945,13.68278,-14.59917,13.67027), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.64556,13.70194,-15.45861,13.70444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.45861,13.70444,-16.64556,13.70194), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.08259,13.70828,-15.45861,13.70444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.52639,13.71583,-12.08259,13.70828), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.81639,13.74111,-15.25167,13.74472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.25167,13.74472,-14.81639,13.74111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.70806,13.77,-16.62722,13.77528), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.62722,13.77528,-16.70806,13.77), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.36472,13.78139,-14.86389,13.78416), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.86389,13.78416,-15.36472,13.78139), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.49139,13.79389,-15.315,13.79528), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.315,13.79528,-16.49139,13.79389), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.95278,13.80833,-15.315,13.79528), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.73695,13.8225,-15.07055,13.82638), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.07055,13.82638,-16.73695,13.8225), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.56695,13.83389,-16.77667,13.83583), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.77667,13.83583,-16.56695,13.83389), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.54611,13.86444,-16.77667,13.83583), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.9425,13.90444,-16.50306,13.93556), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.50306,13.93556,-16.74028,13.96527), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.74028,13.96527,-16.57361,13.98667), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.57361,13.98667,-16.69667,13.99277), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.69667,13.99277,-16.57361,13.98667), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.63139,14.00472,-12.015,14.0125), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.015,14.0125,-16.72111,14.01722), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.72111,14.01722,-12.015,14.0125), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.78139,14.02805,-16.72111,14.01722), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.585,14.04277,-16.78139,14.02805), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.72389,14.06472,-16.585,14.04277), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.65445,14.09333,-16.72389,14.06472), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.46389,14.14555,-16.42056,14.15111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.42056,14.15111,-16.51167,14.15361), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.51167,14.15361,-16.42056,14.15111), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-11.98083,14.16722,-16.87806,14.17889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.87806,14.17889,-16.46889,14.18944), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.46889,14.18944,-16.87806,14.17889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.03111,14.27888,-12.09833,14.30444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.09833,14.30444,-12.03111,14.27888), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.09889,14.36666,-16.94806,14.37555), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.94806,14.37555,-12.09889,14.36666), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.2025,14.40083,-16.94806,14.37555), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.06528,14.455,-12.2025,14.40083), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.17861,14.6075,-12.14778,14.63944), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.14778,14.63944,-17.17583,14.65444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.17583,14.65444,-17.45639,14.66139), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.45639,14.66139,-17.17583,14.65444), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.42306,14.69889,-17.42834,14.72833), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.42834,14.72833,-17.33528,14.73166), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.33528,14.73166,-17.42834,14.72833), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.52,14.76027,-12.24575,14.77217), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.24575,14.77217,-17.52,14.76027), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.43083,14.88778,-17.14611,14.91805), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-17.14611,14.91805,-12.43083,14.88778), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.47889,15.00889,-16.98111,15.0975), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.98111,15.0975,-12.77853,15.14678), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.77853,15.14678,-16.98111,15.0975), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.84972,15.20805,-12.78833,15.20861), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.78833,15.20861,-12.84972,15.20805), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.89361,15.26166,-12.84389,15.27028), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.84389,15.27028,-12.89361,15.26166), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.84583,15.30805,-12.84389,15.27028), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.80056,15.36527,-12.9325,15.36805), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.9325,15.36805,-16.80056,15.36527), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.06028,15.47916,-12.96472,15.50611), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-12.96472,15.50611,-13.10028,15.50889), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.10028,15.50889,-12.96472,15.50611), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.0925,15.58333,-13.24278,15.63861), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.24278,15.63861,-13.0925,15.58333), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.53639,15.78139,-13.24278,15.63861), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.49222,16.05222,-13.39555,16.05527), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.39555,16.05527,-16.49222,16.05222), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.5277,16.06043,-13.39555,16.05527), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.52727,16.07796,-16.50695,16.09416), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.52727,16.07796,-16.50695,16.09416), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.50695,16.09416,-13.46056,16.09499), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.46056,16.09499,-16.50695,16.09416), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.67722,16.09888,-13.46056,16.09499), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.85166,16.11832,-13.67722,16.09888), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.49528,16.14972,-16.46889,16.18055), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.46889,16.18055,-13.71111,16.18499), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.71111,16.18499,-16.46889,16.18055), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.87528,16.19805,-13.71111,16.18499), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.38805,16.21999,-13.97361,16.23721), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.97361,16.23721,-16.38805,16.21999), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-13.96694,16.27805,-13.97361,16.23721), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.98583,16.48999,-16.3,16.5036), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.3,16.5036,-15.55,16.51249), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.55,16.51249,-16.3,16.5036), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.225,16.54777,-16.14611,16.55194), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-16.14611,16.55194,-14.225,16.54777), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.23917,16.55888,-16.14611,16.55194), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.33556,16.57694,-15.46889,16.57972), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.46889,16.57972,-14.33556,16.57694), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.10806,16.58611,-15.46889,16.57972), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.0875,16.61444,-15.04861,16.63027), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.04861,16.63027,-14.33722,16.63249), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.33722,16.63249,-15.04861,16.63027), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.86028,16.63832,-14.37778,16.63999), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.37778,16.63999,-14.86028,16.63832), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.11694,16.64833,-14.37778,16.63999), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-15.09778,16.67111,-14.98111,16.69305), mapfile, tile_dir, 0, 11, "sn-senegal")
	render_tiles((-14.98111,16.69305,-15.09778,16.67111), mapfile, tile_dir, 0, 11, "sn-senegal")