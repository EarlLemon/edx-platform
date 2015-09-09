/**
 * Provides utilities for validating courses during creation, for both new courses and reruns.
 */
define(["jquery", "gettext", "js/views/utils/view_utils", "js/views/utils/create_utils_base"],
    function ($, gettext, ViewUtils, CreateUtilsFactory) {
        "use strict";
        return function (selectors, classes) {
            var keyLengthViolationMessage = gettext("The combined length of the organization, course number, and course run fields cannot be more than <%=limit%> characters.");
            var keyFieldSelectors = [selectors.org, selectors.number, selectors.run];
            // check fields only if they are marked as :required
            var nonEmptyCheckFieldSelectors = _.map(
                [selectors.name, selectors.org, selectors.number, selectors.run],
                function (selector){ return selector + ':required'; }
            );

            CreateUtilsFactory.call(this, selectors, classes, keyLengthViolationMessage, keyFieldSelectors, nonEmptyCheckFieldSelectors);

            this.create = function (courseInfo, errorHandler) {
                $.postJSON(
                    '/course/',
                    courseInfo,
                    function (data) {
                        if (data.url !== undefined) {
                            ViewUtils.redirect(data.url);
                        } else if (data.ErrMsg !== undefined) {
                            errorHandler(data.ErrMsg);
                        }
                    }
                );
            };
        };
    });
