import logging
from collections import namedtuple

import requests

from . import ticket

__author__ = 'dranck, rnester, kshirsal'


class JiraTicket(ticket.Ticket):
    """
    A JIRA Ticket object. Contains JIRA-specific methods for working with tickets.
    """
    def __init__(self, url, project, auth=None, ticket_id=None):
        self.ticketing_tool = 'JIRA'

        # JIRA URLs
        self.url = url
        self.rest_url = '{0}/rest/api/2/issue'.format(self.url)
        if isinstance(auth, tuple):
            self.auth = auth
            self.auth_url = self.url
        else:
            self.auth = 'kerberos'
            self.auth_url = '{0}/step-auth-gss'.format(self.url)

        # Call our parent class's init method which creates our requests session.
        super(JiraTicket, self).__init__(project, ticket_id)

        # Overwrite our request_result namedtuple from Ticket, adding watchers field for JiraTicket.
        Result = namedtuple('Result', ['status', 'error_message', 'url', 'ticket_content', 'watchers'])
        self.request_result = Result('Success', None, self.ticket_url, None, None)

    def _generate_ticket_url(self):
        """
        Generates the ticket URL out of the url, project, and ticket_id.
        :return: ticket_url: The URL of the ticket.
        """
        ticket_url = None

        # If we are receiving a ticket_id, it indicates we'll be doing an update or resolve, so set ticket_url.
        if self.ticket_id:
            if '-' not in self.ticket_id:
                # Adding the project to the beginning of the ticket_id, so that the ticket_id is of the form KEY-XX.
                self.ticket_id = "{0}-{1}".format(self.project, self.ticket_id)
            ticket_url = "{0}/browse/{1}".format(self.url, self.ticket_id)

        # This method is called from set_ticket_id(), _create_ticket_request(), or Ticket.__init__().
        # If this method is being called, we want to update the url field in our Result namedtuple.
        self.request_result = self.request_result._replace(url=ticket_url)

        return ticket_url

    def _verify_project(self, project):
        """
        Queries the JIRA API to see if project is a valid project for the given JIRA instance.
        :param project: The project you're verifying.
        :return: True or False depending on if project is valid.
        """
        try:
            r = self.s.get("{0}/rest/api/2/project/{1}".format(self.url, project))
            logging.debug("Verify project: status code: {0}".format(r.status_code))
            r.raise_for_status()
            logging.debug("Project {0} is valid".format(project))
            return True
        except requests.RequestException as e:
            if r.json()['errorMessages'][0] == "No project could be found with key \'{0}\'.".format(project):
                logging.error("Project {0} is not valid".format(project))
            else:
                logging.error("Unexpected error occurred when verifying project")
                logging.error(e)
            return False

    def _verify_ticket_id(self, ticket_id):
        """
        Queries the JIRA API to see if ticket_id is a valid ticket for the given JIRA instance.
        :param ticket_id: The ticket you're verifying.
        :return: True or False depending on if ticket is valid.
        """
        try:
            r = self.s.get("{0}/{1}".format(self.rest_url, ticket_id))
            logging.debug("Verify ticket_id: status code: {0}".format(r.status_code))
            r.raise_for_status()
            logging.debug("Ticket {0} is valid".format(ticket_id))
            return True
        except requests.RequestException as e:
            if r.json()['errorMessages'][0] == "Issue Does Not Exist":
                logging.error("Ticket {0} is not valid".format(ticket_id))
            else:
                logging.error("Unexpected error occurred when verifying ticket_id")
                logging.error(e)
            return False

    def create(self, summary, description, **kwargs):
        """
        Creates a ticket.
        The required parameters for ticket creation are summary and description.
        Keyword arguments are used for other ticket fields.
        :param summary: The ticket summary.
        :param description: The ticket description.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        error_message = ""
        if summary is None:
            error_message = "summary is a necessary parameter for ticket creation"
        if description is None:
            error_message = "description is a necessary parameter for ticket creation"
        if error_message:
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        # Create our parameters used in ticket creation.
        params = self._create_ticket_parameters(summary, description, kwargs)

        # Create our ticket.
        return self._create_ticket_request(params)

    def _create_ticket_parameters(self, summary, description, fields):
        """
        Creates the payload for the POST request when creating a JIRA ticket.

        The required parameters for ticket creation are summary and description.
        Keyword arguments are used for other ticket fields.

        Fields examples:
        summary='Ticket summary'
        description='Ticket description'
        priority='Major'
        type='Task'
        assignee='username'
        reporter='username'
        environment='Environment Test'
        duedate='2017-01-13'
        parent='KEY-XX'
        customfield_XXXXX='Custom field text'

        :param summary: The ticket summary.
        :param description: The ticket description.
        :param fields: Other ticket fields.
        :return: params: A dictionary to pass in to the POST request containing ticket details.
        """
        # Create our parameters for creating the ticket.
        params = {'fields': {}}
        params['fields'] = {'project': {'key': self.project},
                            'summary': summary,
                            'description': description}

        # Some of the ticket fields need to be in a specific form for the tool.
        fields = _prepare_ticket_fields(fields)

        # Update params dict with items from options_dict.
        params['fields'].update(fields)
        return params

    def _create_ticket_request(self, params):
        """
        Tries to create the ticket through the ticketing tool's API.
        Retrieves the ticket_id and creates the ticket_url.
        :param params: The payload to send in the POST request.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        # Attempt to create ticket.
        try:
            r = self.s.post(self.rest_url, json=params)
            logging.debug("Create ticket: status code: {0}".format(r.status_code))
            r.raise_for_status()
        except requests.RequestException as e:
            error_message = "Error creating ticket - {0}".format(list(r.json()['errors'].values())[0])
            logging.error(error_message)
            logging.error(e)
            return self.request_result._replace(status='Failure', error_message=error_message)

        # Retrieve key from new ticket.
        ticket_content = r.json()
        self.ticket_id = ticket_content['key']
        self.ticket_url = self._generate_ticket_url()
        logging.info("Created ticket {0} - {1}".format(self.ticket_id, self.ticket_url))
        return self.request_result

    def edit(self, **kwargs):
        """
        Edits fields in a JIRA ticket.
        Keyword arguments are used to specify ticket fields.

        Fields examples:
        summary='Ticket summary'
        description='Ticket description'
        priority='Major'
        type='Task'
        assignee='username'
        reporter='username'
        environment='Environment Test'
        duedate='2017-01-13'
        parent='KEY-XX'
        customfield_XXXXX='Custom field text'

        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        # Some of the ticket fields need to be in a specific form for the tool.
        fields = _prepare_ticket_fields(kwargs)

        params = {'fields': fields}

        # Attempt to edit ticket.
        try:
            r = self.s.put("{0}/{1}".format(self.rest_url, self.ticket_id), json=params)
            logging.debug("Edit ticket: status code: {0}".format(r.status_code))
            r.raise_for_status()
            logging.info("Edited ticket {0} - {1}".format(self.ticket_id, self.ticket_url))
            return self.request_result
        except requests.RequestException as e:
            error_message = "Error editing ticket - {0}".format(list(r.json()['errors'].values())[0])
            logging.error(error_message)
            logging.error(e)
            return self.request_result._replace(status='Failure', error_message=error_message)

    def add_comment(self, comment):
        """
        Adds a comment to a JIRA ticket.
        :param comment: A string representing the comment to be added.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        params = {'body': comment}

        # Attempt to add comment to ticket.
        try:
            r = self.s.post("{0}/{1}/comment".format(self.rest_url, self.ticket_id), json=params)
            logging.debug("Add comment: status code: {0}".format(r.status_code))
            r.raise_for_status()
            logging.info("Added comment to ticket {0} - {1}".format(self.ticket_id, self.ticket_url))
            return self.request_result
        except requests.RequestException as e:
            error_message = "Error adding comment to ticket - {0}".format(list(r.json()['errors'].values())[0])
            logging.error(error_message)
            logging.error(e)
            return self.request_result._replace(status='Failure', error_message=error_message)

    def change_status(self, status):
        """
        Changes status of a JIRA ticket.

        To view possible workflow transitions for a particular ticket:
        <self.rest_url>/<self.ticket_id>/transitions

        :param status: Status to change to.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        status_id = self._get_status_id(status)
        if not status_id:
            error_message = "Not a valid status: {0}".format(status)
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        params = {'transition': {}}
        params['transition']['id'] = status_id

        # Attempt to change status of ticket
        try:
            r = self.s.post("{0}/{1}/transitions".format(self.rest_url,  self.ticket_id), json=params)
            logging.debug("Change status: status code: {0}".format(r.status_code))
            r.raise_for_status()
            logging.info("Changed status of ticket {0} - {1}".format(self.ticket_id, self.ticket_url))
            return self.request_result
        except requests.RequestException as e:
            error_message = "Error changing status of ticket"
            logging.error(error_message)
            logging.error(e)
            return self.request_result._replace(status='Failure', error_message=error_message)

    def remove_all_watchers(self):
        """
        Removes all watchers from a JIRA ticket.
        :return: self.request_result: Named tuple containing request status, error_message, url, and watcher info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        watcher_error_count = 0
        watchers_list = self._get_watchers_list()
        for watcher in watchers_list:
            try:
                r = self.s.delete("{0}/{1}/watchers?username={2}".format(self.rest_url, self.ticket_id, watcher))
                logging.debug("Remove watcher {0}: status code: {1}".format(watcher, r.status_code))
                r.raise_for_status()
            except requests.RequestException as e:
                logging.error("Error removing watcher {0} from ticket".format(watcher))
                logging.error(e)
                watcher_error_count += 1

        if watcher_error_count:
            error_message = "Error removing {0} watchers from ticket".format(watcher_error_count)
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)
        else:
            logging.info("Removed watchers from ticket {0} - {1}".format(self.ticket_id, self.ticket_url))
            return self.request_result._replace(watchers=watchers_list)

    def remove_watcher(self, watcher):
        """
        Removes watcher from a JIRA ticket.
        Accepts an email or username.
        :param watcher: Username of watcher to remove.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        # If an email address was passed in for watcher param, extract the 'name' piece.
        if '@' in watcher:
            watcher = "{0}".format(watcher.split('@')[0].strip())

        try:
            r = self.s.delete("{0}/{1}/watchers?username={2}".format(self.rest_url, self.ticket_id, watcher))
            logging.debug("Remove watcher {0}: status code: {1}".format(watcher, r.status_code))
            r.raise_for_status()
            logging.info("Removed watcher {0} from ticket {1} - {2}".format(watcher, self.ticket_id, self.ticket_url))
            return self.request_result
        except requests.RequestException as e:
            error_message = "Error removing watcher {0} from ticket".format(watcher)
            logging.error(error_message)
            logging.error(e)
            return self.request_result._replace(status='Failure', error_message=error_message)

    def add_watcher(self, watcher):
        """
        Adds watcher to a JIRA ticket.
        Accepts an email or username.
        :param watcher: Username of watcher to remove.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        # If an email address was passed in for watcher param, extract the 'name' piece.
        # Add double quotes around the name, which is needed for JIRA API.
        if '@' in watcher:
            watcher = "{0}".format(watcher.split('@')[0].strip())
        watcher = "\"{0}\"".format(watcher)

        # For some reason, if you try to add an empty string as a watcher, it adds the requestor.
        # So, only execute this code if the watcher is not an empty string.
        if watcher:
            try:
                r = self.s.post("{0}/{1}/watchers".format(self.rest_url, self.ticket_id), data=watcher)
                logging.debug("Add watcher {0}: status code: {1}".format(watcher, r.status_code))
                r.raise_for_status()
                logging.info("Added watcher {0} to ticket {1} - {2}".format(watcher, self.ticket_id, self.ticket_url))
                return self.request_result
            except requests.RequestException as e:
                error_message = "Error adding {0} as a watcher to ticket".format(watcher)
                logging.error(error_message)
                logging.error(e)
                return self.request_result._replace(status='Failure', error_message=error_message)
        else:
            error_message = "Error adding {0} as a watcher to ticket".format(watcher)
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

    def add_attachment(self, file_name):
        """
        Attaches a file to a JIRA ticket.
        :param file_name: A string representing the file to attach.
        :return: self.request_result: Named tuple containing request status, error_message, and url info.
        """
        if not self.ticket_id:
            error_message = "No ticket ID associated with ticket object. Set ticket ID with set_ticket_id(<ticket_id>)"
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

        headers = {"X-Atlassian-Token": "nocheck"}

        # Attempt to attach file.
        try:
            params = {'file': open(file_name, 'r')}
            r = self.s.post("{0}/{1}/attachments".format(self.rest_url, self.ticket_id),
                            files=params,
                            headers=headers)
            logging.debug("Add attachment: status code: {0}".format(r.status_code))
            r.raise_for_status()
            logging.info("Attached file {0} to ticket {1} - {2}".format(file_name, self.ticket_id, self.ticket_url))
            return self.request_result
        except requests.RequestException as e:
            error_message = "Error attaching file {0}".format(file_name)
            logging.error(error_message)
            logging.error(e)
            return self.request_result._replace(status='Failure', error_message=error_message)
        except IOError:
            error_message = "File {0} not found".format(file_name)
            logging.error(error_message)
            return self.request_result._replace(status='Failure', error_message=error_message)

    def _get_status_id(self, status_name):
        """
        Gets status id corresponding to status name.
        :param status_name: The name of the status.
        :return: status_id: The id of the status.
        """
        try:
            r = self.s.get('{0}/{1}/transitions'.format(self.rest_url, self.ticket_id))
            logging.debug("Get status id: status code: {0}".format(r.status_code))
            r.raise_for_status()
        except requests.RequestException as e:
            logging.error("Error retrieving JIRA status information")
            logging.error(e)
            return

        status_json = r.json()
        for status in status_json['transitions']:
            if status['to']['name'] == status_name:
                return status['id']

    def _get_watchers_list(self):
        """
        Gets list of watchers on a JIRA ticket.
        :return: watchers_list: List of watchers on a JIRA ticket.
        """
        try:
            # Get watchers list and convert to json.
            r = self.s.get("{0}/{1}/watchers".format(self.rest_url, self.ticket_id))
            logging.debug("Get watcher list: status code: {0}".format(r.status_code))
            r.raise_for_status()
        except requests.RequestException as e:
            logging.error("Error retrieving watchers list")
            logging.error(e)
            return

        watchers_json = r.json()
        watchers_list = []
        for watcher in watchers_json['watchers']:
            watchers_list.append(watcher['name'])

        return watchers_list


def _prepare_ticket_fields(fields):
        """
        Makes sure each key value pair in the fields dictionary is in the correct form.
        :param fields: Ticket fields.
        :return: fields: Ticket fields in the correct form for the ticketing tool.
        """
        for key, value in fields.items():
            if key in ['priority', 'assignee', 'reporter', 'parent']:
                fields[key] = {'name': value}
            if key == 'type':
                fields['issuetype'] = {'name': value}
                fields.pop('type')
        return fields


def main():
    """
    main() function, not directly callable.
    :return:
    """
    print("Not directly executable")


if __name__ == "__main__":
    main()
