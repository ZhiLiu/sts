'''
Classes for tracking replayed events.

Author: sw
'''

from sts.entities import Link
import abc
import logging
import time
log = logging.getLogger("events")

class EventDag(object):
  '''A collection of Event objects. EventDags are primarily used to present a
  view of the underlying events with one external event and all of its
  dependent internal events pruned (see events())
  '''
  def __init__(self, events):
    '''events is a list of EventWatcher objects. Refer to log_parser.parse to
    see how this is assembled.'''
    # we need to the events to be ordered, so we keep a copy of the list
    self._events = events
    self.label2event = {
      event.label : event
      for event in events
    }

  def events(self, pruned_event_or_label=None):
    '''Return a generator of the events in the DAG with pruned event and all of its
    internal dependents pruned'''
    if pruned_event_or_label is not None:
      if type(pruned_event_or_label) == str:
        assert(pruned_label in self.label2event)
        pruned_event = self.label2event[pruned_event_or_label]
        pruned_label = pruned_event_or_label
      else:
        assert(isinstance(pruned_event_or_label,Event))
        pruned_event = pruned_event_or_label
        pruned_label = pruned_event.label
      if not hasattr(pruned_event, 'dependent_labels'):
        raise RuntimeError("Pruned Event %s does not specify dependent_labels" %
                           str(pruned_event))
      pruned_labels = set(pruned_event.dependent_labels)
      pruned_labels.add(pruned_label)
      should_yield = lambda event: event.label not in pruned_labels
    else:
      should_yield = lambda x: True

    for event in self._events:
      if should_yield(event):
        yield event

  def event_watchers(self, pruned_event_or_label=None):
    '''Return a generator of the EventWatchers in the DAG with pruned event and
    all of its internal dependents pruned'''
    for event in self.events(pruned_event_or_label):
      yield EventWatcher(event)

class EventWatcher(object):
  '''EventWatchers watch events. This class can be used to wrap either
  InternalEvents or ExternalEvents to perform pre and post functionality.'''

  def __init__(self, event):
    self.event = event

  def run(self, simulation):
    self._pre()

    while not self.event.proceed(simulation):
      time.sleep(0.2)
      log.debug(".")

    self._post()

  def _pre(self):
    log.debug("Executing %s" % str(self.event))

  def _post(self):
    log.debug("Finished Executing %s" % str(self.event))

class Event(object):
  __metaclass__ = abc.ABCMeta

  def __init__(self, json_hash):
    assert('label' in json_hash)
    self.label = json_hash['label']

  @abc.abstractmethod
  def proceed(self, simulation):
    '''Executes a single `round'. Returns a boolean that is true if the
    Replayer may continue to the next Event, otherwise proceed() again
    later.'''
    pass

  def __str__(self):
    return self.__class__.__name__ + ":" + self.label

# -------------------------------------------------------- #
# Semi-abstract classes for internal and external events   #
# -------------------------------------------------------- #

class InternalEvent(Event):
  '''An InternalEvent is one that happens within the controller(s) under
  simulation. Derivatives of this class verify that the internal event has
  occured in its proceed method before it returns.'''
  def __init__(self, json_hash):
    super(InternalEvent, self).__init__(json_hash)
    # TODO(sw): fingerprinting! this is why we need a separate class for internal events!

  def proceed(self, simulation):
    pass

class InputEvent(Event):
  '''An event that the simulator injects into the simulation. These events are
  assumed to be causally independent.

  Each InputEvent has a list of dependent InternalEvents that it takes in its
  constructor. This enables the pruning of events.'''
  def __init__(self, json_hash):
    super(InputEvent, self).__init__(json_hash)
    if 'dependent_labels' in json_hash:
      self.dependent_labels = json_hash['dependent_labels']

# --------------------------------- #
#  Concrete classes of InputEvents  #
# --------------------------------- #

def assert_switch(json_hash):
  assert('dpid' in json_hash)

def assert_link(json_hash):
  assert('start_dpid' in json_hash)
  assert('start_port_no' in json_hash)
  assert('end_dpid' in json_hash)
  assert('end_port_no' in json_hash)

def assert_controller(json_hash):
  assert('uuid' in json_hash)

class SwitchFailure(InputEvent):
  def __init__(self, json_hash):
    super(SwitchFailure, self).__init__(json_hash)
    assert_switch(json_hash)
    self.dpid = int(json_hash['dpid'])

  def proceed(self, simulation):
    software_switch = simulation.topology.get_switch(self.dpid)
    simulation.topology.crash_switch(software_switch)
    return True

class SwitchRecovery(InputEvent):
  def __init__(self, json_hash):
    super(SwitchRecovery, self).__init__(json_hash)
    assert_switch(json_hash)
    self.dpid = int(json_hash['dpid'])

  def proceed(self, simulation):
    software_switch = simulation.topology.get_switch(self.dpid)
    simulation.topology.recover_switch(software_switch)
    return True

def get_link(link_event, simulation):
  start_software_switch = simulation.topology.get_switch(link_event.start_dpid)
  end_software_switch = simulation.topology.get_switch(link_event.end_dpid)
  link = Link(start_software_switch, link_event.start_port_no,
              end_software_switch, link_event.end_port_no)
  return link

class LinkFailure(InputEvent):
  def __init__(self, json_hash):
    super(LinkFailure, self).__init__(json_hash)
    assert_link(json_hash)
    self.start_dpid = int(json_hash['start_dpid'])
    self.start_port_no = int(json_hash['start_port_no'])
    self.end_dpid = int(json_hash['end_dpid'])
    self.end_port_no = int(json_hash['end_port_no'])

  def proceed(self, simulation):
    link = get_link(self, simulation)
    simulation.topology.sever_link(link)
    return True

class LinkRecovery(InputEvent):
  def __init__(self, json_hash):
    super(LinkRecovery, self).__init__(json_hash)
    assert_link(json_hash)
    self.start_dpid = int(json_hash['start_dpid'])
    self.start_port_no = int(json_hash['start_port_no'])
    self.end_dpid = int(json_hash['end_dpid'])
    self.end_port_no = int(json_hash['end_port_no'])

  def proceed(self, simulation):
    link = get_link(self, simulation)
    simulation.topology.repair_link(link)
    return True

class ControllerFailure(InputEvent):
  def __init__(self, json_hash):
    super(ControllerFailure, self).__init__(json_hash)
    assert_controller(json_hash)
    uuid = json_hash['uuid']
    self.uuid = (uuid[0], int(uuid[1]))

  def proceed(self, simulation):
    controller = simulation.controller_manager.get_controller(self.uuid)
    simulation.controller_manager.kill_controller(controller)
    return True

class ControllerRecovery(InputEvent):
  def __init__(self, json_hash):
    super(ControllerRecovery, self).__init__(json_hash)
    assert_controller(json_hash)
    uuid = json_hash['uuid']
    self.uuid = (uuid[0], int(uuid[1]))

  def proceed(self, simulation):
    controller = simulation.controller_manager.get_controller(self.uuid)
    simulation.controller_manager.reboot_controller(controller)
    return True

class HostMigration(InputEvent):
  def __init__(self, json_hash):
    super(HostMigration, self).__init__(json_hash)
    assert('old_ingress_dpid' in json_hash)
    self.old_ingress_dpid = int(json_hash['old_ingress_dpid'])
    assert('old_ingress_port_no' in json_hash)
    self.old_ingress_port_no = int(json_hash['old_ingress_port_no'])
    assert('new_ingress_dpid' in json_hash)
    self.new_ingress_dpid = int(json_hash['new_ingress_dpid'])
    assert('new_ingress_port_no' in json_hash)
    self.new_ingress_port_no = int(json_hash['new_ingress_port_no'])

  def proceed(self, simulation):
    # TODO(cs): add HostMigrations to Fuzzer
    simulation.topology.migrate_host(self.old_ingress_dpid,
                                     self.old_ingress_port_no,
                                     self.new_ingress_dpid,
                                     self.new_ingress_port_no)
    return True

class PolicyChange(InputEvent):
  def __init__(self, json_hash):
    super(PolicyChange, self).__init__(json_hash)
    assert('request_type' in json_hash)
    self.request_type = json_hash['request_type']

  def proceed(self, simulation):
    # TODO(cs): implement me, and add PolicyChanges to Fuzzer
    pass

class TrafficInjection(InputEvent):
  def __init__(self, json_hash):
    super(TrafficInjection, self).__init__(json_hash)

  def proceed(self, simulation):
    if simulation.dataplane_trace is None:
      raise RuntimeError("No dataplane trace specified!")
    simulation.dataplane_trace.inject_trace_event()
    return True

class WaitTime(InputEvent):
  def __init__(self, json_hash):
    assert('time' in json_hash)
    self.time = json_hash['time']
    super(WaitTime, self).__init__(json_hash)

  def proceed(self, simulation):
    log.info("WaitTime: pausing simulation for %f seconds" % (self.time))
    time.sleep(self.time)
    return True


all_input_events = [SwitchFailure, SwitchRecovery, LinkFailure, LinkRecovery,
                    ControllerFailure, ControllerRecovery, HostMigration,
                    PolicyChange, TrafficInjection, WaitTime]

# ----------------------------------- #
#  Concrete classes of InternalEvents #
# ----------------------------------- #

# Controllers' internal events:

class MastershipChange(InternalEvent):
  def __init__(self, json_hash):
    super(MastershipChange, self).__init__(json_hash)

class TimerEvent(InternalEvent):
  def __init__(self, json_hash):
    super(TimerEvent, self).__init__(json_hash)

# Simulator's internal events:

class DataplaneDrop(InternalEvent):
  def __init__(self, json_hash):
    super(DataplaneDrop, self).__init__(json_hash)
    assert('dpout_id' in json_hash)
    self.dpout_id = json_hash['dpout_id']

  def proceed(self, simulation):
    dp_event = simulation.patch_panel.get_buffered_dp_event(self.dpout_id)
    if dp_event is not None:
      simulation.patch_panel.drop_dp_event(dp_event)
      return True
    return False

class DataplanePermit(InternalEvent):
  def __init__(self, json_hash):
    super(DataplanePermit, self).__init__(json_hash)
    assert('dpout_id' in json_hash)
    self.dpout_id = json_hash['dpout_id']

  def proceed(self, simulation):
    dp_event = simulation.patch_panel.get_buffered_dp_event(self.dpout_id)
    if dp_event is not None:
      simulation.patch_panel.permit_dp_event(dp_event)
      return True
    return False

class ControlplaneReceivePermit(InternalEvent):
  def __init__(self, json_hash):
    super(ControlplaneReceivePermit, self).__init__(json_hash)
    assert('dpid' in json_hash)
    self.dpid = json_hash['dpid']
    assert('controller_uuid' in json_hash)
    self.controller_uuid = (json_hash['controller_uuid'][0],
                            json_hash['controller_uuid'][1])

  def proceed(self, simulation):
    switch = simulation.topology.get_switch(self.dpid)
    connection = switch.get_connection(self.controller_uuid)
    if not connection.io_worker.has_pending_receives():
      return False
    connection.io_worker.permit_receive()
    return True

class ControlplaneSendPermit(InternalEvent):
  def __init__(self, json_hash):
    super(ControlplaneSendPermit, self).__init__(json_hash)
    assert('dpid' in json_hash)
    self.dpid = json_hash['dpid']
    assert('controller_uuid' in json_hash)
    self.controller_uuid = (json_hash['controller_uuid'][0],
                            json_hash['controller_uuid'][1])

  def proceed(self, simulation):
    switch = simulation.topology.get_switch(self.dpid)
    connection = switch.get_connection(self.controller_uuid)
    if not connection.io_worker.has_pending_sends():
      return False
    connection.io_worker.permit_send()
    return True

all_internal_events = [MastershipChange, TimerEvent, DataplaneDrop,
                       DataplanePermit, ControlplaneReceivePermit,
                       ControlplaneSendPermit]