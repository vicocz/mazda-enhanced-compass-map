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
    # Region: FJ
    # Region Name: Fiji

	render_tiles((178.0611,-19.1614,178.16721,-19.16028), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.0611,-19.1614,178.16721,-19.16028), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.16721,-19.16028,178.0611,-19.1614), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.96049,-19.14334,178.1983,-19.14278), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.1983,-19.14278,177.96049,-19.14334), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.13049,-19.12917,178.1983,-19.14278), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.9677,-19.10556,178.13049,-19.12917), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.1725,-19.07056,178.16409,-19.04834), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.16409,-19.04834,178.46941,-19.03028), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.46941,-19.03028,178.33411,-19.02917), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.33411,-19.02917,178.46941,-19.03028), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.1714,-19,178.30299,-18.99917), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.30299,-18.99917,178.1714,-19), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.49049,-18.96973,178.30299,-18.99917), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.3772,-18.92945,178.49049,-18.96973), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.0002,-18.26389,178.0491,-18.26195), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.0002,-18.26389,178.0491,-18.26195), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.0491,-18.26195,178.0002,-18.26389), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.7466,-18.22195,178.0491,-18.26195), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.4619,-18.15362,178.58611,-18.13806), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.58611,-18.13806,178.4619,-18.15362), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.3488,-18.11612,178.58611,-18.13806), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.5322,-18.09223,177.3027,-18.08084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.3027,-18.08084,178.5322,-18.09223), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.6974,-18.04723,177.3027,-18.08084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.66859,-18.01223,178.6974,-18.04723), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.5858,-17.89917,178.6194,-17.88834), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.6194,-17.88834,177.2563,-17.87973), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.2563,-17.87973,178.6194,-17.88834), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.3694,-17.83056,177.2563,-17.87973), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.4252,-17.76417,178.5647,-17.75473), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.5647,-17.75473,177.3644,-17.75223), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.3644,-17.75223,178.5647,-17.75473), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.4238,-17.69084,178.5986,-17.68251), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.5986,-17.68251,177.4238,-17.69084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.38609,-17.65751,178.59109,-17.63584), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.59109,-17.63584,177.38609,-17.65751), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.46719,-17.55584,178.44051,-17.55417), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.44051,-17.55417,177.46719,-17.55584), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.24609,-17.47723,178.3725,-17.47501), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.3725,-17.47501,178.24609,-17.47723), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.64439,-17.43612,178.29691,-17.43167), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.29691,-17.43167,177.64439,-17.43612), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.8286,-17.42667,178.29691,-17.43167), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.9594,-17.40917,178.28081,-17.40306), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.28081,-17.40306,177.9269,-17.40112), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.9269,-17.40112,178.28081,-17.40306), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((177.8075,-17.3875,177.9269,-17.40112), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.2738,-17.36973,177.8075,-17.3875), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.19299,-17.30112,178.2738,-17.36973), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.7619,-17.00528,178.7002,-17.00251), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.7619,-17.00528,178.7002,-17.00251), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.7002,-17.00251,178.7619,-17.00528), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.8102,-16.90806,178.9588,-16.90639), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.9588,-16.90639,178.8102,-16.90806), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.0164,-16.89528,178.9588,-16.90639), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.8877,-16.86056,179.0164,-16.89528), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.51801,-16.81612,179.29469,-16.81362), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.29469,-16.81362,178.51801,-16.81612), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.5797,-16.80612,179.05299,-16.80056), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.05299,-16.80056,179.1205,-16.79528), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.1205,-16.79528,179.05299,-16.80056), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.60049,-16.78612,178.4789,-16.78167), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.4789,-16.78167,178.60049,-16.78612), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.8705,-16.77334,178.4789,-16.78167), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.55969,-16.76362,179.48019,-16.75445), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.48019,-16.75445,179.1311,-16.75084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.1311,-16.75084,179.6425,-16.74834), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.6425,-16.74834,179.1311,-16.75084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.9519,-16.74195,179.3558,-16.73945), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.3558,-16.73945,179.9519,-16.74195), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.80051,-16.72334,179.3558,-16.73945), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.52831,-16.70667,178.5661,-16.70167), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.5661,-16.70167,178.52831,-16.70667), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.2722,-16.69139,178.5661,-16.70167), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.7019,-16.67501,179.88721,-16.67084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.88721,-16.67084,178.5477,-16.66695), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.5477,-16.66695,179.88721,-16.67084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.8474,-16.66695,179.88721,-16.67084), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.58771,-16.65278,178.6344,-16.64223), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.6344,-16.64223,178.53439,-16.63417), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.53439,-16.63417,178.6344,-16.64223), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.7775,-16.59917,179.5744,-16.59584), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.5744,-16.59584,178.8188,-16.59473), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.8188,-16.59473,179.5744,-16.59584), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.9194,-16.56001,178.8188,-16.59473), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.63161,-16.52279,179.9194,-16.56001), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((178.9819,-16.46973,179.94189,-16.46445), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.94189,-16.46445,178.9819,-16.46973), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.4005,-16.41306,179.3472,-16.39306), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.3472,-16.39306,179.4005,-16.41306), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.8127,-16.35667,179.3472,-16.39306), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.4313,-16.31834,179.8127,-16.35667), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.61411,-16.2439,179.77271,-16.23056), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.77271,-16.23056,179.61411,-16.2439), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.76579,-16.18334,179.9895,-16.15269), mapfile, tile_dir, 0, 11, "fj-fiji")
	render_tiles((179.9895,-16.15269,179.76579,-16.18334), mapfile, tile_dir, 0, 11, "fj-fiji")