# Copyright (C) 2021 Collabora Limited
# Author: Guillaume Tucker <guillaume.tucker@collabora.com>
#
# This module is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import json
import requests
import urllib.parse

from cloudevents.http import from_json

from kernelci.data import Database


class KernelCI_API(Database):

    def __init__(self, config, token):
        super().__init__(config, token)
        if self._token is None:
            raise ValueError("API token required for kernelci_api")
        self._headers = {
            'Authorization': f'Bearer {self._token}',
            'Content-Type': 'application/json',
        }
        self._filters = {}

    def _make_url(self, path):
        return urllib.parse.urljoin(self.config.url, path)

    def _get(self, path):
        url = self._make_url(path)
        resp = requests.get(url, headers=self._headers)
        resp.raise_for_status()
        return resp

    def _post(self, path, data=None):
        url = self._make_url(path)
        resp = requests.post(url, headers=self._headers, data=data)
        resp.raise_for_status()
        return resp

    def _put(self, path, data=None):
        url = self._make_url(path)
        resp = requests.put(url, headers=self._headers, data=data)
        resp.raise_for_status()
        return resp

    def subscribe(self, channel):
        resp = self._post(f'subscribe/{channel}')
        return json.loads(resp.text)['id']

    def subscribe_node_channel(self, filters=None):
        resp = self._post(f'subscribe/node')
        sub_id = json.loads(resp.text)['id']
        self._filters[sub_id] = filters
        return sub_id

    def unsubscribe(self, sub_id):
        if sub_id in self._filters:
            self._filters.pop(sub_id)
        self._post(f'unsubscribe/{sub_id}')

    def get_event(self, sub_id):
        path = '/'.join(['listen', str(sub_id)])
        resp = self._get(path)
        return from_json(resp.json().get('data'))

    def get_node(self, node_id):
        resp = self._get('/'.join(['node', node_id]))
        return json.loads(resp.text)

    def get_nodes_by_commit_hash(self, commit_hash):
        """
        Get list of node objects matching the commit SHA-1
        provided to 'nodes' endpoint
        """
        resp = self._get('?'.join(['nodes', 'revision.commit='+commit_hash]))
        return resp.json()

    def get_node_from_event(self, event):
        return self.get_node(event.data['id'])

    def pubsub_event_filter(self, sub_id, event):
        """Filter Pub/Sub events

        Filter received Pub/Sub event using provided filter dictionary.
        Return True if the event matches with the filter, otherwise False.
        """
        event_filter_status = True
        filters = self._filters.get(sub_id)
        if not filters:
            return event_filter_status
        for key, value in filters.items():
            if key not in event.keys():
                continue
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in event.get(key):
                        continue
                    if sub_value != event.get(key).get(sub_key):
                        return
            elif value != event[key]:
                return

        return event

    def receive_node(self, sub_id):
        """
        Listen to all the events on 'node' channel and apply filter on it.
        Return node if event matches with the filter.
        """
        path = '/'.join(['listen', str(sub_id)])
        try:
            while True:
                resp = self._get(path)
                event = from_json(resp.json().get('data'))
                node = self.get_node_from_event(event)
                node['op'] = event.data['op']
                if self.pubsub_event_filter(sub_id, node):
                    return node
        except Exception as e:
            print(f"Error: {e}")
        except KeyboardInterrupt as e:
            print(f"Stopping.")

    def submit(self, data, verbose=False):
        obj_list = []
        for path, item in data.items():
            try:
                node_id = item.get('_id')
                if node_id:
                    resp = self._put(f"{path}/{node_id}", json.dumps(item))
                else:
                    resp = self._post(path, json.dumps(item))
            except requests.exceptions.HTTPError as ex:
                self._print_http_error(ex, verbose)
                raise(ex)
            obj = json.loads(resp.text)
            obj_list.append(obj)
        return obj_list


def get_db(config, token):
    """Get a KernelCI API database object"""
    return KernelCI_API(config, token)
