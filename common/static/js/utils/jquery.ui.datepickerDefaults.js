define(["module", "jquery", "jquery.ui"], function(module, $, ui) {
    var format_translation = {
        '%Y': 'yy',
        '%y': 'y',
        '%m': 'mm',
        '%d': 'dd',
        '%b': 'M', //short month name, locale-aware
        '%B': 'MM' // full month name, locale-aware
    }
    // get python date format from default require config, alt format specified for tests
    var dateFormat = module.config().dateFormatPython || '%Y-%m-%d';
    for (var directive in format_translation){
        dateFormat = dateFormat.replace(directive, format_translation[directive]);
    }
    $.datepicker.setDefaults($.extend(
            {dateFormat: dateFormat},
            module.config().defaults
    ));
});
