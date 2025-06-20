#!/usr/bin/python3
# -*- coding: utf-8 -*-

# DroneBL.py - A single file DroneBL RPC2 interaction tool.
#
# Copyright (C) 2025 Matthew Beeching
#
# This file is part of DroneBL.py.
#
# DroneBL.py is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# DroneBL.py is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with DroneBL.py. If not, see <http://www.gnu.org/licenses/>.

import argparse, datetime, io, ipaddress, json, os.path, re, sys
import xml.etree.ElementTree as et
import http.client

homedir = os.path.expanduser('~')
defconffile = os.path.join(homedir, '.dronebl')

config = {'rpckey': None, 'staging': False, 'debug': False}

parser = None

def checkint(val):
	try:
		return int(val)
	except:
		return None

def ipaddr(val):
	try:
		ipn = ipaddress.ip_network(val, False)
		ipa = ipn.network_address
		if ipn.prefixlen == ipa.max_prefixlen:
			return ipa
		else:
			return ipn
	except:
		return None

def idorip(val):
	i = checkint(val)
	if i is None:
		i = ipaddr(val)
		if i is None:
			raise ValueError('value must be either an integer, an IP address or a CIDR address')
		return i
	return i

def portnumber(val):
	port = int(val)
	if port < 1:
		raise ValueError('value must be greater than 0')
	if port > 65535:
		raise ValueError('value must be less than 65536')
	return port

def listingtype(val):
	type = int(val)
	if type < 1:
		raise ValueError('value must be greater than 0')
	if type > 255:
		raise ValueError('value must be less than 256')
	return type

def querylimit(val):
	lim = int(val)
	if lim < 1:
		raise ValueError('value must be greater than 0')
	if lim > 255:
		raise ValueError('value must be less than 1001')
	return lim

def positiveint(val):
	i = int(val)
	if i < 1:
		raise ValueError('value must be greater than 0')
	return i

def parse_args(conffile=defconffile):
	global args, parser

	parser = argparse.ArgumentParser(add_help=False)
	parser.add_argument('-h', '-?', '--help', help='Show this help message and exit', action='help')
	parser.add_argument('-r', '--rpckey', help='Specify an RPC key to use (overrides config/environment)', action='store', dest='rpckey', default=None)
	parser.add_argument('-c', '--config', help='Specify a configuration file to use', action='store', dest='conffile', default=conffile)
	parser.add_argument('-s', '--staging', help='Do not modify DroneBL, only stage requests', action='store_true', dest='staging', default=False)
	subparsers = parser.add_subparsers(title='command', help='Available commands', dest='command')
	subparsers.required = True

	sparser_help = subparsers.add_parser('help', help='Show this help message and exit')

	sparser_typelist = subparsers.add_parser('types', help='Show a list of available listing types')

	sparser_query = subparsers.add_parser('query', help='Query DroneBL for entries')
	sparser_query.add_argument('idorip', help='ID or IP address to lookup', action='store', nargs='+', type=idorip)
	sparser_query.add_argument('-o', '--own', help='Only show records owned by the RPC key used', dest='own', action='store_true', default=False)
	sparser_query.add_argument('-l', '--listed', help='Show only records with listed being either 0 (not active), 1 (Active)', dest='listed', action='store', default=None, type=int, choices=range(0, 3), metavar='{0,1}')
	sparser_query.add_argument('-t', '--type', help='Show only results with the specified type', dest='type', action='store', default=None, type=listingtype, metavar='{1-255}')
	sparser_query.add_argument('-s', '--start', help='A unix timestamp specifying the start offset of results to show', dest='start', action='store', default=None, type=int)
	sparser_query.add_argument('-e', '--stop', help='A unix timestamp specifying the ending offset of results to show', dest='stop', action='store', default=None, type=int)
	sparser_query.add_argument('-n', '--limit', help='Limit the number or records to the specified number', dest='limit', action='store', default=None, type=querylimit, metavar='{1-1000}')

	sparser_add = subparsers.add_parser('add', help='Add an entry to DroneBL')
	sparser_add.add_argument('ip', help='IP address to be added', action='store', nargs='+', type=ipaddr)
	sparser_add.add_argument('-t', '--type', help='Specify the type for IPs being added', dest='type', action='store', default=None, type=listingtype, metavar='{1-255}', required=True)
	sparser_add.add_argument('-p', '--port', help='The port associated with the new listing, if applicable', dest='port', action='store', default=None, type=portnumber, metavar='{1-65535}')
	sparser_add.add_argument('-c', '--comment', help='A comment to ba associayed with the new listing', dest='comment', action='store', default=None)
	sparser_add.epilog = 'Note: type, port and comment options apply to all IP addresses supplied'

	sparser_remove = subparsers.add_parser('remove', help='Remove an entry from DroneBL')
	sparser_remove.add_argument('id', help='Listing ID to remove', action='store', nargs='+', type=positiveint)

	sparser_modify = subparsers.add_parser('update', help='Update an entry on DroneBL')
	sparser_modify.add_argument('id', help='Listing ID to update', action='store', nargs='+', type=positiveint)
	sparser_modify.add_argument('-c', '--comment', help='A comment to ba applied to the specified listing(s)', dest='comment', action='store', required=True)

	sparser_config = subparsers.add_parser('config', help='Display or modify local configuration')
	sparser_config.add_argument('-r', '--rpckey', help='Specify an RPC key to save to config', action='store', dest='rpckey', default=None)
	sparser_config.add_argument('-s', '--staging', help='Enable or disable staging', action='store', dest='staging', choices=['yes', 'no'], default=None)
	sparser_config.add_argument('-d', '--debug', help=argparse.SUPPRESS, action='store', dest='debug', choices=['yes', 'no'], default=None)

	args = parser.parse_args()

def load_config():
	global args, config

	if not os.path.isfile(args.conffile):
		return

	newconfig = None
	try:
		fc = open(args.conffile, 'r')
		newconfig = json.load(fc)
		fc.close()
	except:
		pass

	if newconfig is None:
		return

	if 'rpckey' in newconfig:
		config['rpckey'] = newconfig['rpckey']
	if 'staging' in newconfig:
		config['staging'] = newconfig['staging']
	if 'debug' in newconfig:
		config['debug'] = newconfig['debug']

def get_rpcrequest():
	global config

	root = et.Element('request')
	root.set('key', config['rpckey'])
	if config['staging']:
		root.set('staging', '1')
	if config['debug']:
		root.set('debug', '1')

	return root

def req_addmethod(req, method, *args, **kwargs):
	try:
		el = et.SubElement(req, method, **kwargs)
	except Exception as ex:
		print('Error adding request method: ' + str(ex))

def get_rawxml(root):
	try:
		vf = io.BytesIO()
		tree = et.ElementTree(root)
		tree.write(vf, encoding='UTF-8', xml_declaration=True)
		xmlraw = vf.getvalue()
		vf.close()
		return xmlraw
	except Exception as ex:
		print('Error generating request body XML: ' + str(ex))
		sys.exit(-1)

def send_rpcrequest(req, printxmlres=False):
	try:
		xmlreq = get_rawxml(req)
		conn = http.client.HTTPSConnection("dronebl.org")
		conn.request("POST", "/rpc2", xmlreq)
		response = conn.getresponse()
		xmlres = response.read().decode('utf-8')
		conn.close()

		xmlobj = et.fromstring(xmlres)
	except Exception as ex:
		print('Error retrieving RPC response: ' + str(ex))

	if xmlobj.tag != 'response':
		print('Error: invalid XML response received...')
		sys.exit(-1)
	if not 'type' in xmlobj.attrib:
		print('Error: missing response type attribute...')
		sys.exit(-1)
	if not xmlobj.attrib['type'] in ['success', 'error']:
		print('Error: Unknown response type received: ' + xmlobj.attrib['type'])
		sys.exit(-1)
	if xmlobj.attrib['type'] == 'error':
		code = xmlobj.find('./code').text
		message = xmlobj.find('./message').text
		data = xmlobj.find('./data').text
		print('Error received from RPC server:')
		print('')
		print('Code:    ' + code)
		print('Message: ' + message)
		print('Data:    ' + data)
		sys.exit(-1)

	ret = {}

	if printxmlres:
		print(xmlres)

	for el in xmlobj:
		if not el.tag in ret:
			ret[el.tag] = []
		ret[el.tag].append(el.attrib.copy())

	return ret

def show_rpcrequest(req):
	xmlreq = get_rawxml(req).decode('utf-8')
	print(xmlreq)

def show_success(res):
	global args, config

	if not 'success' in res:
		return

	for dbg in res['success']:
		msg = dbg['data']
		params = []
		for k in dbg:
			if k == 'data':
				continue
			params.append(k + '=' + str(dbg[k]))
		info = ', '.join(params)
		if len(info) > 0:
			info = ' (' + info + ')'
		print('Success: ' + msg + info)

def show_warnings(res):
	global args, config

	if not 'warning' in res:
		return

	for dbg in res['warning']:
		msg = dbg['data']
		params = []
		for k in dbg:
			if k == 'data':
				continue
			params.append(k + '=' + str(dbg[k]))
		info = ', '.join(params)
		if len(info) > 0:
			info = ' (' + info + ')'
		print('WARNING: ' + msg + info)

def show_debuginfo(res):
	global args, config

	if not config['debug']:
		return

	if not 'debug' in res:
		return

	for dbg in res['debug']:
		msg = dbg['data']
		params = []
		for k in dbg:
			if k == 'data':
				continue
			params.append(k + '=' + str(dbg[k]))
		info = ', '.join(params)
		if len(info) > 0:
			info = ' (' + info + ')'
		print('Debug: ' + msg + info)

def do_help():
	parser.print_help()
	sys.exit(0)

def do_config():
	global args, config

	if args.rpckey is None and args.staging is None and args.debug is None:
		print('Configuration:')
		print('')
		if config['rpckey'] is not None:
			print('RPC Key: %s' % (config['rpckey']))
		else:
			print('RPC Key: not set')
		if config['staging']:
			print('Staging: Yes')
		else:
			print('Staging: No')
		if config['debug']:
			print('Debug: Yes')
		return

	if args.staging == 'yes':
		config['staging'] = True
	elif args.staging == 'no':
		config['staging'] = False

	if args.debug == 'yes':
		config['debug'] = True
	elif args.debug == 'no':
		config['debug'] = False

	if args.rpckey is not None:
		config['rpckey'] = args.rpckey

	try:
		fc = open(args.conffile, 'w')
		newconfig = json.dump(config, fc)
		fc.close()
	except Exception as ex:
		print('Unable to update configuration: %s' % (str(ex)))
		sys.exit(1)

	print('Configuration updated')

def do_types():
	req = get_rpcrequest()
	req_addmethod(req, 'typelist')
	res = send_rpcrequest(req)

	if not 'typelist' in res:
		print('Error: missing typelist')
		return

	desclen = 0
	for type in res['typelist']:
		if len(type['description']) > desclen:
			desclen = len(type['description'])
	desclen = desclen + 1

	print('Type  Description')
	print('===== '.ljust(desclen+6, '='))
	for type in res['typelist']:
		print(str(type['type']).ljust(6) + type['description'])

	show_warnings(res)

def do_query():
	global args, config

	startts = datetime.datetime.now()

	req = get_rpcrequest()

	kwargs = {}
	if args.own:
		kwargs['own'] = '1'
	if args.limit is not None:
		kwargs['limit'] = str(args.limit)
	if args.listed is not None:
		kwargs['listed'] = str(args.listed)
	if args.type is not None:
		kwargs['type'] = str(args.type)
	if args.start is not None:
		kwargs['start'] = str(args.start)
	if args.stop is not None:
		kwargs['stop'] = str(args.stop)

	for item in args.idorip:
		if isinstance(item, int):
			req_addmethod(req, 'lookup', id=str(item), **kwargs)
		else:
			req_addmethod(req, 'lookup', ip=str(item), **kwargs)

	res = send_rpcrequest(req)

	cols = {'timestamp': ['Time', 5], 'id': ['ID', 3], 'ip': ['IP', 3], 'type': ['Type', 5], 'listed': ['Listed', 7], 'comment': ['Comment', 8]}

	results = []
	if 'result' in res:
		for r in res['result']:
			if 'timestamp' in r:
				dt = datetime.datetime.fromtimestamp(int(r['timestamp']))
				r['timestamp'] = dt.isoformat()
			for k in cols:
				if not k in r:
					continue
				if len(r[k]) > cols[k][1]:
					cols[k][1] = len(r[k]) + 1
			results.append(r)

		headtext = ''
		headline = ''
		for k in cols:
			if len(headtext) > 0:
				headtext = headtext + ' '
				headline = headline + ' '
			headtext = headtext + cols[k][0].ljust(cols[k][1])
			headline = headline + ('=' * cols[k][1])

		print(headtext)
		print(headline)

		for r in results:
			line = ''
			for k in cols:
				if len(line) > 0:
					line = line + ' '
				line = line + r[k].ljust(cols[k][1])
			print(line)

	endts = datetime.datetime.now()
	delay = endts - startts

	show_warnings(res)
	show_debuginfo(res)

	print(str(len(results)) + ' results found in ' + str(delay))

def do_add():
	global args, config

	startts = datetime.datetime.now()

	req = get_rpcrequest()

	kwargs = {}
	if args.type is not None:
		kwargs['type'] = str(args.type)
	if args.port is not None:
		kwargs['port'] = str(args.port)
	if args.comment is not None:
		kwargs['comment'] = args.comment

	for ip in args.ip:
		req_addmethod(req, 'add', ip=str(ip), **kwargs)

	res = send_rpcrequest(req)

	show_success(res)

	show_warnings(res)
	show_debuginfo(res)

	endts = datetime.datetime.now()
	delay = endts - startts

	print('Completed in ' + str(delay))

def do_remove():
	global args, config

	startts = datetime.datetime.now()

	req = get_rpcrequest()

	for id in args.id:
		req_addmethod(req, 'remove', id=str(id))

	res = send_rpcrequest(req)

	show_success(res)

	show_warnings(res)
	show_debuginfo(res)

	endts = datetime.datetime.now()
	delay = endts - startts

	print('Completed in ' + str(delay))

def do_update():
	global args, config

	startts = datetime.datetime.now()

	req = get_rpcrequest()

	kwargs = {}
	if args.comment is not None:
		kwargs['comment'] = args.comment

	for id in args.id:
		req_addmethod(req, 'update', id=str(id), **kwargs)

	res = send_rpcrequest(req)

	show_success(res)

	show_warnings(res)
	show_debuginfo(res)

	endts = datetime.datetime.now()
	delay = endts - startts

	print('Completed in ' + str(delay))

cmds = {
	'help': do_help,
	'config': do_config,
	'types': do_types,
	'query': do_query,
	'add': do_add,
	'remove': do_remove,
	'update': do_update
	}

parse_args()
load_config()

if args.rpckey is not None:
	config['rpckey'] = args.rpckey

if args.command != 'config':
	if config['rpckey'] is None:
		parser.error('the following arguments are required: -r/--rpckey')

if args.command in cmds:
	cmds[args.command]()
else:
	print('Error: unhandled command: ' + args.command)
	print(str(args))
	sys.exit(-1)
