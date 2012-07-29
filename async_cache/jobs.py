import time
import logging

from django.core.cache import cache

from async_cache import tasks

logger = logging.getLogger(__name__)

MEMCACHE_MAX_EXPIRATION = 2592000


class AsyncCacheJob(object):
    # Default cache lifetime is 5 minutes
    lifetime = 600
    # Default behaviour is to do a synchronous fetch when the cache is empty.
    # Stale results are generally ok, but not no results.
    fetch_on_empty = True

    def get(self, *args, **kwargs):
        """
        Return the data for this function (using the cache if possible).
        """
        key = self.key(*args, **kwargs)
        result = cache.get(key)
        if result is None:
            # Cache is empty - we can either:
            # a) fetch the data immediately, blocking execution until
            #    the fetch has finished, or
            # b) trigger an async refresh
            if self.fetch_on_empty:
                logger.debug("Job %s with key '%s' - cache MISS - calling refresh",
                             self.class_path, key)
                return self.refresh(*args, **kwargs)
            else:
                logger.debug(("Job %s with key '%s' - cache MISS - triggering "
                              "async refresh and returning empty result"),
                             self.class_path, key)
                self.async_refresh(key, *args, **kwargs)
                return self.empty()

        if result[0] < time.time():
            # Cache is stale - we trigger a refresh but allow the stale result
            # to be returned this time
            logger.debug(("Job %s with key '%s' - stale cache HIT - triggering "
                          "async refresh and returning stale result"),
                         self.class_path, key)
            self.async_refresh(key, *args, **kwargs)
        else:
            logger.debug(("Job %s with key '%s' - cache HIT"), self.class_path,
                         key)
        return result[1]

    def refresh(self, *args, **kwargs):
        """
        Fetch the result SYNCHRONOUSLY and populate the cache
        """
        result = self.fetch(*args, **kwargs)
        cache.set(self.key(*args, **kwargs),
                  (self.time_to_live(*args, **kwargs), result),
                  MEMCACHE_MAX_EXPIRATION)
        return result

    def async_refresh(self, key, *args, **kwargs):
        """
        Trigger an asynchronous job to refresh the cache
        """
        tasks.refresh_cache.delay(self.class_path, *args, **kwargs)

    @property
    def class_path(self):
        return '%s.%s' % (self.__module__, self.__class__.__name__)

    # Override these methods

    def empty(self):
        """
        Return the appropriate value for a cache MISS (and when we defer the
        repopulation of the cache)
        """
        return None

    def time_to_live(self, *args, **kwargs):
        """
        Return the TTL for this item.
        """
        return time.time() + self.lifetime

    def key(self, *args, **kwargs):
        """
        Return the cache key to use.

        If no parameters are passed to the 'get' method then this method doesn
        not need to be overridden.
        """
        if not args and not kwargs:
            return self.class_path
        if args and not kwargs:
            return args
        return "%s-%s" % (args, kwargs)

    def fetch(self, *args, **kwargs):
        """
        Return the data for this job - this is where the expensive work should
        be encapsulated.
        """
        raise NotImplementedError()
