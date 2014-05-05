import csv
import json
import glob
import os
import romanesco.uri
from StringIO import StringIO

def has_header(sample):
    # Creates a dictionary of types of data in each column. If any
    # column is of a single type (say, integers), *except* for the first
    # row, then the first row is presumed to be labels. If the type
    # can't be determined, it is assumed to be a string in which case
    # the length of the string is the determining factor: if all of the
    # rows except for the first are the same length, it's a header.
    # Finally, a 'vote' is taken at the end for each column, adding or
    # subtracting from the likelihood of the first row being a header.
    #
    # This is from Python's csv.py, with an added condition so empty cells
    # don't result in inconsistent columns.

    rdr = csv.reader(StringIO(sample), csv.Sniffer().sniff(sample))

    header = rdr.next() # assume first row is header

    columns = len(header)
    columnTypes = {}
    for i in range(columns): columnTypes[i] = None

    checked = 0
    for row in rdr:
        # arbitrary number of rows to check, to keep it sane
        if checked > 20:
            break
        checked += 1

        if len(row) != columns:
            continue # skip rows that have irregular number of columns

        for col in columnTypes.keys():

            # don't penalize empty cells
            if row[col] == "":
                continue

            for thisType in [int, long, float, complex]:
                try:
                    thisType(row[col])
                    break
                except (ValueError, OverflowError):
                    pass
            else:
                # fallback to length of string
                thisType = len(row[col])

            # treat longs as ints
            if thisType == long:
                thisType = int

            if thisType != columnTypes[col]:
                if columnTypes[col] is None: # add new column type
                    columnTypes[col] = thisType
                else:
                    # type is inconsistent, remove column from
                    # consideration
                    del columnTypes[col]

    # finally, compare results against first row and "vote"
    # on whether it's a header
    hasHeader = 0
    for col, colType in columnTypes.items():
        if type(colType) == type(0): # it's a length
            if len(header[col]) != colType:
                hasHeader += 1
            else:
                hasHeader -= 1
        else: # attempt typecast
            try:
                colType(header[col])
            except (ValueError, TypeError):
                hasHeader += 1
            else:
                hasHeader -= 1

    return hasHeader > 0

def csv_to_rows(input, *pargs, **kwargs):
    header = has_header('\n'.join(input[:2048].splitlines()))
    if header:
        reader = csv.DictReader(input.splitlines(), *pargs, **kwargs)
        rows = [d for d in reader]
        fields = reader.fieldnames
    else:
        reader = csv.reader(input.splitlines(), *pargs, **kwargs)
        rows = [{"Column " + str(index + 1): value for index, value in enumerate(row)} for row in reader]
        fields = []
        if len(rows) > 0:
            fields = ["Column " + str(index + 1) for index in range(len(rows[0]))]

    output = {"fields": fields, "rows": rows}

    # Attempt numeric conversion
    for row in output["rows"]:
        for col in row:
            try:
                row[col] = int(row[col])
            except:
                try:
                    row[col] = float(row[col])
                except:
                    pass

    return output

def vtkrow_to_dict(attributes, i):
    row = {}
    for c in range(attributes.GetNumberOfArrays()):
        variant_value = attributes.GetAbstractArray(c).GetVariantValue(i)
        if variant_value.IsInt():
            value = variant_value.ToInt()
        elif variant_value.IsLong():
            value = variant_value.ToLong()
        elif variant_value.IsDouble() or variant_value.IsFloat():
            value = variant_value.ToDouble()
        else:
            value = variant_value.ToString()
        row[attributes.GetAbstractArray(c).GetName()] = value
    return row

def dict_to_vtkarrays(row, fields, attributes):
    import vtk
    for key in fields:
        value = row[key]
        if isinstance(value, (int, long, float)):
            arr = vtk.vtkDoubleArray()
        elif isinstance(value, str):
            arr = vtk.vtkStringArray()
        elif isinstance(value, unicode):
            arr = vtk.vtkUnicodeStringArray()
        else:
            arr = vtk.vtkStringArray()
        arr.SetName(key)
        attributes.AddArray(arr)    

def dict_to_vtkrow(row, attributes):
    for key in row:
        value = row[key]
        if not isinstance(value, (int, long, float, str, unicode)):
            value = str(value)
        found = False
        for i in range(attributes.GetNumberOfArrays()):
            arr = attributes.GetAbstractArray(i)
            if arr.GetName() == key:
                arr.InsertNextValue(value)
                found = True
                break
        if not found:
            raise Exception("[dict_to_vtkrow] Unexpected key: " + key)

converters = {}
validators = {}

def import_converters(search_paths):
    """
    Import converters and validators from the specified search paths.
    These functions are loaded into the dictionaries
    ``romanesco.format.converters`` and ``romanesco.format.validators``
    and are made available to :py:func:`romanesco.convert`
    and :py:func:`romanesco.isvalid`.

    Any files in a search path matching ``validate_*.json`` are loaded
    as validators. Validators should be fast (ideally O(1)) algorithms
    for determining if data is of the specified format. These are algorithms
    that have a single input named ``"input"`` and a single output named
    ``"output"``. The input has the type and format to be checked.
    The output must have type and format ``"boolean"``. The script performs
    the validation and sets the output variable to either true or false.

    Any other ``.json`` files are imported as convertes.
    A converter is simply an analysis with one input named ``"input"`` and one
    output named ``"output"``. The input and output should have matching
    type but should be of different formats.

    :param search_paths: A list of search paths relative to the current
        working directory.
    """

    prevdir = os.getcwd()
    for path in search_paths:
        os.chdir(path)
        for filename in glob.glob(os.path.join(path, "*.json")):
            with open(filename) as f:
                analysis = json.load(f)

            if not "script" in analysis:
                analysis["script"] = romanesco.uri.get_uri(analysis["script_uri"])

            if os.path.basename(filename).startswith("validate_"):

                # This is a validator
                in_type = analysis["inputs"][0]["type"]
                in_format = analysis["inputs"][0]["format"]
                if in_type not in validators:
                    validators[in_type] = {}
                validators[in_type][in_format] = analysis

            else:

                # This is a converter
                in_type = analysis["inputs"][0]["type"]
                in_format = analysis["inputs"][0]["format"]
                out_format = analysis["outputs"][0]["format"]
                if in_type not in converters:
                    converters[in_type] = {}
                analysis_type = converters[in_type]
                if in_format not in analysis_type:
                    analysis_type[in_format] = {}
                input_format = analysis_type[in_format]
                if out_format not in input_format:
                    input_format[out_format] = {}
                input_format[out_format] = [analysis]

    os.chdir(prevdir)
    
    max_steps = 3
    for i in range(max_steps):
        to_add = []
        for analysis_type, analysis_type_values in converters.iteritems():
            for input_format, input_format_values in analysis_type_values.iteritems():
                for output_format, converter in input_format_values.iteritems():
                    if output_format in analysis_type_values:
                        for next_output_format, next_converter in analysis_type_values[output_format].iteritems():
                            if input_format != next_output_format and next_output_format not in input_format_values:
                                to_add.append((analysis_type, input_format, next_output_format, converter + next_converter))
        for c in to_add:
            converters[c[0]][c[1]][c[2]] = c[3]

def print_conversion_graph():
    """
    Print a graph of supported conversion paths in DOT format to standard output.
    """

    print "digraph g {"
    for analysis_type, analysis_type_values in converters.iteritems():
        for input_format, input_format_values in analysis_type_values.iteritems():
            for output_format in input_format_values:
                print '"' + analysis_type + ":" + input_format + '" -> "' + analysis_type + ":" + output_format + '"'
    print "}"

def print_conversion_table():
    """
    Print a table of supported conversion paths in CSV format with ``"from"`` and ``"to"`` columns
    to standard output.
    """

    print "from,to"
    for analysis_type, analysis_type_values in converters.iteritems():
        for input_format, input_format_values in analysis_type_values.iteritems():
            for output_format in input_format_values:
                print analysis_type + ":" + input_format + "," + analysis_type + ":" + output_format

def import_default_converters():
    """
    Import converters from the default search paths. This is called when the
    :py:mod:`romanesco.format` module is first loaded.
    """

    cur_path = os.path.dirname(os.path.realpath(__file__))
    import_converters([os.path.join(cur_path, t) for t in ["r", "table", "tree", "string", "number", "image", "boolean"]])

import_default_converters()