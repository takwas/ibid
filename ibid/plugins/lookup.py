from urllib2 import urlopen
from urllib import urlencode, quote
from time import time
from datetime import datetime
from simplejson import loads
import re

import feedparser

from ibid.plugins import Processor, match, handler
from ibid.config import Option
from ibid.utils import ago, decode_htmlentities, get_html_parse_tree

help = {}

help['bash'] = u'Retrieve quotes from bash.org.'
class Bash(Processor):
    u"bash[.org] (random|<number>)"

    feature = 'bash'

    @match(r'^bash(?:\.org)?\s+(random|\d+)$')
    def bash(self, event, quote):
        soup = get_html_parse_tree('http://bash.org/?%s' % quote.lower())

        if quote.lower() == "random":
            number = u"".join(soup.find('p', 'quote').find('b').contents)
            event.addresponse(u"%s:" % number)

        quote = soup.find('p', 'qt')
        if not quote:
            event.addresponse(u"There's no such quote, but if you keep talking like that maybe there will be.")
        else:
            for line in quote.contents:
                if str(line) != '<br />':
                    event.addresponse(unicode(line).strip())

help['lastfm'] = u'Lists the tracks last listened to by the specified user.'
class LastFm(Processor):
    u"last.fm for <username>"

    feature = "lastfm"

    @match(r'^last\.?fm\s+for\s+(\S+?)\s*$')
    def listsongs(self, event, username):
        songs = feedparser.parse("http://ws.audioscrobbler.com/1.0/user/%s/recenttracks.rss?%s" % (username, time()))
        if songs['bozo']:
            event.addresponse(u"No such user")
        else:
            event.addresponse(u', '.join(u'%s (%s ago)' % (e.title, ago(datetime.utcnow() - datetime.strptime(e.updated, '%a, %d %b %Y %H:%M:%S +0000'), 1)) for e in songs['entries']))

help['lotto'] = u"Gets the latest lotto results from the South African National Lottery."
class Lotto(Processor):
    u"""lotto"""

    feature = 'lotto'
    
    errors = {
      'open': 'Something went wrong getting to the Lotto site',
      'balls': 'I expected to get %s balls, but found %s. They were: %s',
    }
    
    za_url = 'http://www.nationallottery.co.za/'
    za_re = re.compile(r'images/balls/ball_(\d+).gif')
    za_text = u'Latest lotto results for South Africa, Lotto: '
    
    @match(r'lotto(\s+for\s+south\s+africa)?')
    def za(self, event, za):
        try:
            f = urlopen(self.za_url)
        except Exception, e:
            event.addresponse(self.errors['open'])
            return
        
        s = "".join(f)
        f.close()
        
        r = self.za_text
        
        balls = self.za_re.findall(s)
        
        if len(balls) != 14:
            event.addresponse(self.errors['balls'] % \
                (14, len(balls), ", ".join(balls)))
            return
        
        r += u" ".join(balls[:6])
        r += u" (Bonus: %s), Lotto Plus: " % (balls[6], )
        r += u" ".join(balls[7:13])
        r += u" (Bonus: %s)" % (balls[13], )
        event.addresponse(r)

help['fml'] = u'Retrieves quotes from fmylife.com.'
class FMyLife(Processor):
    u"""fml (<number>|random)"""

    feature = "fml"

    def remote_get(self, id):
        soup = get_html_parse_tree('http://www.fmylife.com/' + str(id))

        quote = soup.find('div', id='wrapper').div.p
        if quote:
            url = u"http://www.fmylife.com" + quote.find('a', 'fmllink')['href']
            quote = u"".join(tag.contents[0] for tag in quote.findAll(True))

            return u'%s: "%s"' % (url, quote)

    @match(r'^(?:fml\s+|http://www\.fmylife\.com/\S+/)(\d+|random)$')
    def fml(self, event, id):
        event.addresponse(self.remote_get(id) or u"No such quote")

help["microblog"] = u"Looks up messages on microblogging services like twitter and identica."
class Twitter(Processor):
    u"""latest (tweet|identica) from <name>
    (tweet|identica) <number>"""

    feature = "microblog"

    default = { 'twitter': 'http://twitter.com/',
                'tweet': 'http://twitter.com/',
                'identica': 'http://identi.ca/api/',
                'identi.ca': 'http://identi.ca/api/',
              }
    services = Option('services', 'Micro blogging services', default)

    def setup(self):
        self.update.im_func.pattern = re.compile(r'^(%s)\s+(\d+)$' % ('|'.join(self.services.keys()),))
        self.latest.im_func.pattern = re.compile(r'^(?:latest|last)\s+(%s)\s+(?:update\s+)?(?:by\s+|from\s+)?(\S+)$' % ('|'.join(self.services.keys()),))

    def remote_update(self, service, id):
        f = urlopen('%sstatuses/show/%s.json' % (self.services[service], id))
        status = loads(f.read())
        f.close()

        return u'%s: "%s"' % (status['user']['screen_name'], status['text'])

    def remote_latest(self, service, user):
        f = urlopen('%sstatuses/user_timeline/%s.json?count=1' % (self.services[service], user))
        statuses = loads(f.read())
        f.close()

        return u'"%s"' % (statuses[0]['text'])

    @handler
    def update(self, event, service, id):
        event.addresponse(self.remote_update(service.lower(), int(id)))

    @handler
    def latest(self, event, service, user):
        event.addresponse(self.remote_latest(service.lower(), user))

    @match(r'^https?://(?:www\.)?twitter\.com/[^/ ]+/statuse?s?/(\d+)$')
    def twitter(self, event, id):
        event.addresponse(self.remote_update('twitter', int(id)))

    @match(r'^https?://(?:www\.)?identi.ca/notice/(\d+)$')
    def identica(self, event, id):
        event.addresponse(self.remote_update('identi.ca', int(id)))

help['currency'] = u'Converts amounts between currencies.'
class Currency(Processor):
    u"""exchange <amount> <currency> for <currency>
    currencies for <country>"""

    feature = "currency"

    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://www.xe.com/'}
    currencies = {}

    def _load_currencies(self):
        etree = get_html_parse_tree('http://www.xe.com/iso4217.php', headers=self.headers, treetype='etree')

        tbl_main = [x for x in etree.getiterator('table') if x.get('class') == 'tbl_main'][0]

        self.currencies = {}
        for tbl_sub in tbl_main.getiterator('table'):
            if tbl_sub.get('class') == 'tbl_sub':
                for tr in tbl_sub.getiterator('tr'):
                    code, place = [x.text for x in tr.getchildren()]
                    name = u""
                    if not place:
                        place = u""
                    if "," in place[1:-1]:
                        place, name = place.split(',', 1)
                    self.currencies[code] = (place.strip(), name.strip())

    @match(r'^(exchange|convert)\s+([0-9.]+)\s+(\S+)\s+(?:for|to|into)\s+(\S+)$')
    def exchange(self, event, command, amount, frm, to):
        if not self.currencies:
            self._load_currencies()

        if frm not in self.currencies or to not in self.currencies:
            if command.lower() == "exchange":
                event.addresponse("Sorry, I don't know about a currency called %s" % (frm not in self.currencies and frm or to))
            return

        data = {'Amount': amount, 'From': frm, 'To': to}
        etree = get_html_parse_tree('http://www.xe.com/ucc/convert.cgi', urlencode(data), self.headers, 'etree')

        result = u" ".join(tag.text for tag in etree.getiterator('h2'))
        if result:
            event.addresponse(result)
        else:
            event.addresponse(u"The bureau de change appears to be closed for lunch")

    @match(r'^(?:currency|currencies)\s+for\s+(?:the\s+)?(.+)$')
    def currency(self, event, place):
        if not self.currencies:
            self._load_currencies()

        search = re.compile(place, re.I)
        results = []
        for code, (place, name) in self.currencies.iteritems():
            if search.search(place):
                results.append('%s uses %s (%s)' % (place, name, code))

        if results:
            event.addresponse(u', '.join(results))
        else:
            event.addresponse(u'No currencies found')

help['weather'] = u'Retrieves current weather and forecasts for cities.'
class Weather(Processor):
    u"""weather in <city>
    forecast for <city>"""

    feature = "weather"

    defaults = {    'ct': 'Cape Town, South Africa',
                    'jhb': 'Johannesburg, South Africa',
                    'joburg': 'Johannesburg, South Africa',
               }
    places = Option('places', 'Alternate names for places', defaults)
    labels = ('temp', 'humidity', 'dew', 'wind', 'pressure', 'conditions', 'visibility', 'uv', 'clouds', 'ymin', 'ymax', 'ycool', 'sunrise', 'sunset', 'moonrise', 'moonset', 'moonphase', 'metar')
    whitespace = re.compile('\s+')

    class WeatherException(Exception):
        pass

    class TooManyPlacesException(WeatherException):
        pass

    def _text(self, string):
        if not isinstance(string, basestring):
            string = ''.join(string.findAll(text=True))
        return self.whitespace.sub(' ', string).strip()

    def _get_page(self, place):
        if place.lower() in self.places:
            place = self.places[place.lower()]

        soup = get_html_parse_tree('http://m.wund.com/cgi-bin/findweather/getForecast?brand=mobile_metric&query=' + quote(place))

        if soup.body.center and soup.body.center.b.string == 'Search not found:':
            raise Weather.WeatherException(u'City not found')

        if soup.table.tr.th and soup.table.tr.th.string == 'Place: Temperature':
            places = []
            for td in soup.table.findAll('td'):
                places.append(td.find('a', href=re.compile('.*html$')).string)
            raise Weather.TooManyPlacesException(places)

        return soup

    def remote_weather(self, place):
        soup = self._get_page(place)
        tds = soup.table.table.findAll('td')

        values = {'place': tds[0].findAll('b')[1].contents[0], 'time': tds[0].findAll('b')[0].contents[0]}
        for index, td in enumerate(tds[2::2]):
            values[self.labels[index]] = self._text(td)

        return values

    def remote_forecast(self, place):
        soup = self._get_page(place)
        forecasts = []

        for td in soup.findAll('table')[2].findAll('td', align='left'):
            day = td.b.contents[0]
            forecast = td.contents[2]
            forecasts.append('%s: %s' % (day, self._text(forecast)))

        return forecasts

    @match(r'^weather\s+(?:(?:for|at|in)\s+)?(.+)$')
    def weather(self, event, place):
        try:
            values = self.remote_weather(place)
            event.addresponse(u'In %(place)s at %(time)s: %(temp)s; Humidity: %(humidity)s; Wind: %(wind)s; Conditions: %(conditions)s; Sunrise/set: %(sunrise)s/%(sunset)s; Moonrise/set: %(moonrise)s/%(moonset)s' % values)
        except Weather.TooManyPlacesException, e:
            event.addresponse(u'Too many places match %s: %s' % (place, '; '.join(e.message)))
        except Weather.WeatherException, e:
            event.addresponse(e.message)

    @match(r'^forecast\s+(?:for\s+)?(.+)$')
    def forecast(self, event, place):
        try:
            event.addresponse(u', '.join(self.remote_forecast(place)))
        except Weather.TooManyPlacesException, e:
            event.addresponse(u'Too many places match %s: %s' % (place, '; '.join(e.message)))
        except Weather.WeatherException, e:
            event.addresponse(e.message)

# vi: set et sta sw=4 ts=4:
