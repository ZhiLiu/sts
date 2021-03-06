# Copyright 2011-2013 Colin Scott
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import namedtuple
import unittest
import sys
import os
import time

sys.path.append(os.path.dirname(__file__) + "/../../..")

from sts.controller_manager import *
from sts.util.network_namespace import *
from sts.util.io_master import *
from pox.openflow.software_switch import *
from sts.entities import FuzzSoftwareSwitch

class UserSpaceControllerPatchPanelTest(unittest.TestCase):
  def _setup_patch_panel(self, create_io_worker):
    # Have two net_ns processes ping eachother, and verify that the pings go through.
    p = UserSpaceControllerPatchPanel(create_io_worker)
    ping1_addr = "192.168.1.3"
    ping2_addr = "192.168.1.4"
    (ping1_proc, ping1_eth_addr, ping1_host_device) = launch_namespace("ping -c 1 %s" % ping2_addr, ping1_addr, 1)
    p.register_controller("c1", ping1_eth_addr, ping1_host_device)

    (ping2_proc, ping2_eth_addr, ping2_host_device) = launch_namespace("ping -c 1 %s" % ping1_addr, ping2_addr, 2)
    p.register_controller("c2", ping2_eth_addr, ping2_host_device)
    return p

  def test_without_host_ips_set(self):
    if os.geteuid() != 0: # Must be run as root
      return

    io_master = IOMaster()
    p = self._setup_patch_panel(io_master.create_worker_for_socket)

    # TODO(cs): this number is super finicky. Figure out a better way to
    # ensure that all packets have been processed.
    for i in xrange(10):
      io_master.select(timeout=0.2)

    # TODO(cs): verify that at least 2 ICMP replies have been buffered.

  def test_blocking(self):
    if os.geteuid() != 0: # Must be run as root
      return

    p = self._setup_patch_panel(io_master.create_worker_for_socket)
    p.block_controller_pair("c1", "c2")

    # TODO(cs): this number is super finicky. Figure out a better way to
    # ensure that all packets have been processed.
    for i in xrange(10):
      io_master.select(timeout=0.2)

    # TODO(cs): verify that no ICMP replies have been buffered.
    # TODO(cs): unblock the controllers and verify that something goes
    # through.

MockControllerInfo = namedtuple('MockControllerInfo', ['address', 'port', 'cid'])

class OVSControllerPatchPanelTest(unittest.TestCase):
  def test_basic(self):
    p = None
    try:
      io_master = IOMaster()
      p = OVSControllerPatchPanel(io_master.create_worker_for_socket)
      # Wire up a SoftwareSwitch (as a lightweight substitute for OVS) to connect
      # to the patch panel's POX forwarder, and verify that it gets initialized.
      switch = FuzzSoftwareSwitch(5, ports=[])
      controller_info = MockControllerInfo("127.0.0.1", OVSControllerPatchPanel.of_port, "c1")
      switch.add_controller_info(controller_info)
      def create_connection(info, switch, max_backoff_seconds=32):
        socket = connect_socket_with_backoff(info.address, info.port,
                                             max_backoff_seconds=max_backoff_seconds)
        io_worker = io_master.create_worker_for_socket(socket)
        return OFConnection(io_worker)
      switch.connect(create_connection)

      # TODO(cs): this number is super finicky. Figure out a better way to
      # ensure that all packets have been processed.
      for i in xrange(10):
        io_master.select(timeout=0.2)
    finally:
      if p is not None:
        p.clean_up()
