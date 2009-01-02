from cStringIO import StringIO
from time import strftime
from datetime import datetime

from bzrlib.branch import Branch
from bzrlib import log

import ibid
from ibid.plugins import Processor, match
from ibid.utils import ago

help = {'bzr': 'Retrieves commit logs from a Bazaar repository.'}

class LogFormatter(log.LogFormatter):

	def log_revision(self, revision):
		self.to_file.write('Commit %s by %s %s ago: %s\n' % (revision.revno, self.short_author(revision.rev), ago(datetime.now() - datetime.fromtimestamp(revision.rev.timestamp), 2), revision.rev.message.replace('\n', ' ')))

class Bazaar(Processor):
	"""last commit | commit <revno>"""
	feature = 'bzr'

	def setup(self):
		self.branch = Branch.open(self.repository)

	@match(r'^(?:last\s+)?commit(?:\s+(\d+))?$')
	def commit(self, event, revno):
		last = self.branch.revision_id_to_revno(self.branch.last_revision())

		if revno:
			revno = int(revno)
			if revno < 1 or revno > last:
				event.addresponse(u'No such revision')
				return
		else:
			revno = last

		f=StringIO();
		log.show_log(self.branch, LogFormatter(f), start_revision=revno, end_revision=revno, limit=1)
		f.seek(0)
		commits = f.readlines()

		for commit in commits:
			if event.source == 'http':
				event.addresponse({'reply': commit.strip(), 'source': self.source, 'target': self.channel})
			else:
				event.addresponse(commit.strip())
