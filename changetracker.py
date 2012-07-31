"""
Changetracker
A filesystem monitor
"""

import os, time, threading, pickle, hashlib, copy

class ChangeTracker ():
	"""
	Monitors a directory for changes
	"""
	def __init__ (self, path = None, interval = 1.0, handler = None, threaded = True):
		
		# path to be watched
		self.path = os.getcwd () if path is None else path
		# seconds between two updates
		self.interval = interval
		# object, to be notified via callbacks
		self.handler = DefaultChangeHandler () if handler is None else handler	
		# dict with TrackeItem objects where the itempath is the key
		self.allitems = {}
		
		self.running = False
		self.suspended = False

		# changetracker thread if threading is wished
		self.thread = threading.Thread (target=self.run) if threaded else None
	
	def start (self):
	
		if self.thread is None:
			self.run ()
		else:
			self.thread.start ()
	
	def run (self):
		"""
		This runs the ChangeTracker after its creation and terminates,
		when self.running becomes False
		Do not call this method, instead call start()
		"""
		self.running = True
		while self.running:
			if not self.suspended:
				self.update ()
			time.sleep (self.interval)
	
	def suspend (self):
	
		self.suspended = True
	
	def resume (self):
	
		self.suspended = False
	
	def stop (self):
	
		self.running = False
	
	def savestate (self, filename = None):
	
		pickleditems = { i.path : copy.copy (i) for i in self.allitems.values() }
		for i in pickleditems.values():
			i.ct = None
		pickleditems = pickle.dumps (pickleditems)
		#pickleditems = pickleditems.replace ("\r\n", "\n")
	
		if filename is None:
			 filename = self.__class__.__name__
		fs = open (filename, "wb")
		fs.write (pickleditems)
		fs.close()
	
	def loadstate (self, filename = None):
	
		if filename is None:
			filename = self.__class__.__name__
		try:
			fs = open (filename, "rb")
			pickleditems = fs.read()
			fs.close()
			self.allitems = pickle.loads (pickleditems)
			for i in self.allitems.values():
				i.ct = self
		except IOError:
			pass
	
	def update (self):
	
		removeditems = self.allitems.copy()
		addeditems = {}
		changeditems = {}
		moveditems = {}
		
		for itempath in recursive_list (self.path):
			itempath = itempath[len(self.path)+1:]
			itempath = itempath.replace ("\\", "/")
			if itempath in removeditems:
				del removeditems [itempath]
			item = self.allitems [itempath] if itempath in self.allitems else None
			if item is None:
				item = TrackedItem (itempath, self)
				self.allitems [itempath] = item
				addeditems [itempath] = item
			elif item.update ():
				changeditems [itempath] = item
		
		addedhashes = [ i.hash for i in addeditems.values() ]
		for removeditem in removeditems.values():
			if removeditem.itemtype == "file" and removeditem.hash in addedhashes:
				addeditem = [i for i in addeditems.values() if i.hash==removeditem.hash] [0]
				del addeditems [addeditem.path]
				del removeditems [removeditem.path]
				del self.allitems [removeditem.path]
				removeditem.move (addeditem.path, addeditem.hash)
				moveditem = removeditem
				self.allitems [moveditem.path] = moveditem
				moveditems [moveditem.path] = moveditem
		
		for removeditem in	removeditems.values():
			if not self.handler is None:
				self.handler.on_removed (removeditem)
			del self.allitems [removeditem.path]
		
		if not self.handler is None:
			for i in addeditems.values():
				self.handler.on_added (i)
			for i in changeditems.values():
				self.handler.on_changed (i)
			for i in moveditems.values():
				self.handler.on_moved (i)

class TrackedItem:
	
	def __init__ (self, path, ct):
	
		# full path of the item in the filesystem
		# the pathname is the key attribute of the TrackedItem
		self.path = path
		
		# the parenting changetracker
		self.ct = ct
		
		# old path before last movement
		self.oldpath = None
						
		self.update (init=True)
	
	def __cmp__ (self, other):
	
		if other.__class__ != TrackedItem:
			return 1
		elif self.path < other.path:
			return -1
		elif self.path > other.path:
			return 1
		else:
			return 0
	
	def __str__ (self):
	
		if self.itemtype is None:
			return "(NONEXISTING:"+self.abspath()+")"
		elif self.itemtype == "file":
			return "("+self.abspath()+", "+str(self.modtime)+", "+self.itemtype+", "+ \
				self.hash.encode("hex")+")"
		else:
			return "("+self.abspath()+", "+str(self.modtime)+", "+self.itemtype+")"
	
	def __repr__ (self):
	
		return str(self)
	
	def abspath (self):
	
		return os.path.join (self.ct.path, self.path)
		
	def update (self, init=False, dohash=True):
		"""
		Updates the current state (itemtype, existence) and modtime of the item
		return True if modtime has changed on a file, False otherwise
		"""
		
		# itemtype = one of "link", "file", "dir", None
		if os.path.islink (self.abspath()):
			self.itemtype = "link"
		elif os.path.isfile (self.abspath()):
			self.itemtype = "file"
		elif os.path.isdir (self.abspath()):
			self.itemtype = "dir"
		else:
			self.itemtype = None
		
		# md5 hash if it is a file
		if dohash:
			self.hashfile ()
		else:
			self.hash = None
		
		# last modification time if it is a file
		if self.itemtype == "file":
			newmodtime = os.stat(self.abspath()).st_mtime
			if init:
				self.modtime = newmodtime
			elif newmodtime > self.modtime:
				self.modtime = newmodtime
				return True
		else:
			self.modtime = None
		
		return False
	
	def hashfile (self):
	
		if self.itemtype == "file":
			m = hashlib.md5 ()
			fs = open (self.abspath(), "rb")
			while True:
				block = fs.read (32)
				if block == "":
					break
				m.update (block)
			self.hash = m.digest ()
			fs.close ()
		else:
			self.hash = None
	
	def move (self, newpath, newhash=None):
	
		if newpath != self.path:
			self.oldpath = self.path
			self.path = newpath
			if newhash is None:
				self.update ()
			else:
				self.update (dohash=False)
				self.hash = newhash

class DefaultChangeHandler:

	def on_changed (self, item):
	
		print item,"was changed"

	def on_removed (self, item):
	
		print item,"was removed"

	def on_added (self, item):
	
		print item,"was added"

	def on_moved (self, item):
	
		print item,"was moved from",item.oldpath

def recursive_list (rootpath):
	"""
	Generates all paths of subordinate items in the directory "rootpath"
	doesn't follow symlinks
	"""
	for itemname in os.listdir (rootpath) :
		itempath = os.path.join (rootpath, itemname)
		yield itempath
		if not os.path.islink (itempath) and os.path.isdir (itempath) :
			for i in  recursive_list (itempath) :
				yield i

if __name__ == "__main__":

	try:
		ct = ChangeTracker ()
		ct.loadstate ()
		ct.start ()
		while True:
			time.sleep(2)
	except KeyboardInterrupt:
		ct.stop()
		ct.savestate()

	print "kthxbye"

