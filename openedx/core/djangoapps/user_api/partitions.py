"""
Provides partition support to the user service.
"""

import random
import user_service

from xmodule.partitions.partitions import UserPartitionError


class RandomUserPartitionScheme(object):
    """
    This scheme randomly assigns users into the partition's groups.
    """
    RANDOM = random.Random()

    @classmethod
    def get_group_for_user(cls, course_id, user, user_partition, track_function=None):
        """
        Returns the group from the specified user position to which the user is assigned.
        If the user has not yet been assigned, a group will be randomly chosen for them.
        """
        partition_key = cls._key_for_partition(user_partition)
        group_id = user_service.get_course_tag(user, course_id, partition_key)
        group = user_partition.get_group(int(group_id)) if not group_id is None else None
        if group is None:
            if not user_partition.groups:
                raise UserPartitionError('Cannot assign user to an empty user partition')

            # pylint: disable=fixme
            # TODO: had a discussion in arch council about making randomization more
            # deterministic (e.g. some hash).  Could do that, but need to be careful not
            # to introduce correlation between users or bias in generation.
            group = cls.RANDOM.choice(user_partition.groups)

            # persist the value as a course tag
            user_service.set_course_tag(user, course_id, partition_key, group.id)

            if track_function:
                # emit event for analytics
                # FYI - context is always user ID that is logged in, NOT the user id that is
                # being operated on. If instructor can move user explicitly, then we should
                # put in event_info the user id that is being operated on.
                event_info = {
                    'group_id': group.id,
                    'group_name': group.name,
                    'partition_id': user_partition.id,
                    'partition_name': user_partition.name
                }
                # pylint: disable=fixme
                # TODO: Use the XBlock publish api instead
                track_function('xmodule.partitions.assigned_user_to_partition', event_info)

        return group

    @classmethod
    def _key_for_partition(cls, user_partition):
        """
        Returns the key to use to look up and save the user's group for a given user partition.
        """
        return 'xblock.partition_service.partition_{0}'.format(user_partition.id)
