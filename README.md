triggr-server
=============

	- Exposes an API to generate and forward events between devices (currently, from Android phones to Windows PCs).
	- Maintains persistant connections with PCs
		- This is done using Twisted, an event-based Python server framework (Having many concurrent socket connections managed by threads produces too much overhead)
