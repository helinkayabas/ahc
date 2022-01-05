from Ahc import \
    ComponentModel, \
    ComponentRegistry, \
    EventTypes, \
    GenericMessage, \
    GenericMessageHeader, \
    Lock, \
    Event, \
    Thread, \
    Topology
from GSRQueueElement import GSQQueueElement
import time


class RoutingGSRComponent(ComponentModel):
    update_message_type = "GSRUPDATE"
    terminate_routing_message_type = "GSRTERMINATEROUTING"
    routing_completed_message_type = "GSRROUTINGCOMPLETED"

    sleep_duration = 0.1

    def __init__(self, component_name, component_id):
        super(RoutingGSRComponent, self).__init__(component_name, component_id)
        self.terminated = False
        self.routing_completed = False
        self.neighbors = []
        self.n_nodes = 1
        self.distances = {}
        self.link_states = {}
        self.sequence_numbers = {}
        self.next_hop = {}
        self.message_queue = []
        self.queue_lock = Lock()

    def on_init(self, eventobj: Event):
        super(RoutingGSRComponent, self).on_init(eventobj)
        self.neighbors = Topology().get_neighbors(self.componentinstancenumber)

        self.n_nodes = self.componentinstancenumber
        for element in ComponentRegistry().components:
            if "MachineLearningNode" in element:
                component_id = int(element.split("RoutingGSRComponent")[1])
                self.n_nodes = max(self.n_nodes, component_id + 1)

        self.distances = {i: -1 for i in range(self.n_nodes)}
        empty_link_state = {i: -1 for i in range(self.n_nodes)}
        self.link_states = {i: empty_link_state.copy() for i in range(self.n_nodes)}
        self.sequence_numbers = {i: -1 for i in range(self.n_nodes)}
        self.next_hop = {i: -1 for i in range(self.n_nodes)}

        self.distances[self.componentinstancenumber] = 0
        self.link_states[self.componentinstancenumber][self.componentinstancenumber] = 0
        self.sequence_numbers[self.componentinstancenumber] = 0
        self.next_hop[self.componentinstancenumber] = self.componentinstancenumber

        thread = Thread(target=self.job, args=[14, 23])
        thread.start()

    def on_message_from_bottom(self, eventobj: Event):
        message_header = eventobj.eventcontent.header
        message_destination = message_header.messageto.split("-")[0]
        if message_destination == RoutingGSRComponent.__name__:
            message_source_id = message_header.messagefrom.split("-")[1]
            message_type = message_header.messagetype
            content = eventobj.eventcontent.payload

            if message_type == self.update_message_type:
                self.queue_lock.acquire()
                self.message_queue.append(GSQQueueElement(message_source_id, content))
                self.queue_lock.release()
                print(
                    "RECEIVED [" + message_header.messagefrom + " -> " + message_header.messageto + "]: " + str(content)
                )

    def on_message_from_peer(self, eventobj: Event):
        message_header = eventobj.eventcontent.header
        message_destination = message_header.messageto.split("-")[0]
        message_type = message_header.messagetype
        if message_destination == RoutingGSRComponent.__name__:
            if message_type == self.terminate_routing_message_type:
                self.terminated = True

    def job(self, *arg):
        while not self.terminated:
            self.queue_lock.acquire()
            for pkt in self.message_queue:
                self.pkt_process(pkt)
            self.message_queue = []
            self.queue_lock.release()
            self.find_shortest_paths()
            self.broadcast_routing_update()
            time.sleep(self.sleep_duration)

    def pkt_process(self, pkt: GSQQueueElement):
        self.link_states[self.componentinstancenumber][pkt.source_id] = pkt.transfer_duration
        for i in range(self.n_nodes):
            if i != self.componentinstancenumber and pkt.sequence_numbers[i] > self.sequence_numbers[i]:
                self.sequence_numbers[i] = pkt.sequence_numbers[i]
                self.link_states[i] = pkt.link_states[i].copy()

    def broadcast_routing_update(self):
        self.sequence_numbers[self.componentinstancenumber] += 1
        message_from = RoutingGSRComponent.__name__ + "-" + str(self.componentinstancenumber)
        payload = {
            "link_states": self.link_states,
            "sequence_numbers": self.sequence_numbers,
            "timestamp": time.time() * 1000
        }

        for neighbor_id in self.neighbors:
            message_to = RoutingGSRComponent.__name__ + "-" + str(neighbor_id)
            interface_id = str(self.componentinstancenumber) + "-" + str(neighbor_id)
            message_header = GenericMessageHeader(
                self.update_message_type,
                message_from,
                message_to,
                interfaceid=interface_id
            )
            message = GenericMessage(message_header, payload)
            event = Event(self, EventTypes.MFRT, message)
            print("SENDING [" + message_from + " -> " + message_to + "]: " + str(payload))
            self.send_down(event)

    def report_route(self):
        message_from = RoutingGSRComponent.__name__ + "-" + str(self.componentinstancenumber)
        message_to = "Coordinator-" + str(self.componentinstancenumber)
        message_header = GenericMessageHeader(self.routing_completed_message_type, message_from, message_to)
        payload = {"routing_table": self.next_hop}
        message = GenericMessage(message_header, payload)
        event = Event(self, EventTypes.MFRP, message)
        print("SENDING [" + message_from + " -> " + message_to + "]: " + str(payload))
        self.send_peer(event)

    def find_shortest_paths(self):
        processed_nodes = [self.componentinstancenumber]
        self.distances[self.componentinstancenumber] = 0
        for i in range(self.n_nodes):
            if self.link_states[self.componentinstancenumber][i] >= 0:
                self.distances[i] = self.link_states[self.componentinstancenumber][i]
                self.next_hop[i] = i
            else:
                self.distances[i] = -1
                self.next_hop[i] = -1

        while len(processed_nodes) < self.n_nodes:
            node_k = 0
            node_l = 0
            min_w = -1
            for k in range(self.n_nodes + 1):
                if k in processed_nodes:
                    continue
                for l in processed_nodes:
                    if self.link_states[l][k] == -1:
                        continue
                    w = self.distances[l] + self.link_states[l][k]
                    if min_w == -1 or w < min_w:
                        node_k = k
                        node_l = l
                        min_w = w
            if min_w == -1:
                break
            processed_nodes.append(node_k)
            self.distances[node_k] = min_w
            self.next_hop[node_k] = self.next_hop[node_l]

        self.routing_completed = len(processed_nodes) == self.n_nodes
