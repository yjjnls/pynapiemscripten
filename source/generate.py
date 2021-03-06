import os
import re
import template
import json

func_pattern = 'select_overload<(?P<return_type>.*)[(](?P<args_list>.*)[)].*>[(][&](?P<fun_name>((?!,).)*)[)(.*)]'


def arg_template(types):
    result = []
    for arg_type in types:
        result += ['%s' % arg_type, '%s&' % arg_type, 'const %s' % arg_type, 'const %s&' % arg_type]
    return result


class Gen:
    def __init__(self, target, supplement):
        self.target = target
        try:
            portion = os.path.splitext(target)
            with open(portion[0] + '.json', 'r') as f:
                self.supplemental_file_fp = f
                self.supplemental_file = json.loads(f.read())
        except:
            self.supplemental_file_fp = None
            self.supplemental_file = None

        self.supplement = supplement['supplement']
        self.namespace = supplement['namespace']
        self.base_path = os.path.dirname(os.path.realpath(target))

        self.classes = {}
        self.value_objects = {}
        self.value_arrays = {}
        self.global_functions = {}
        self.vectors = {}
        self.pattern = func_pattern
        self.register_content = ''
        self.napi_declaration = ''

    def genfile_start(self):
        if not os.path.exists(os.path.join(self.base_path, 'plugin')):
            os.mkdir(os.path.join(self.base_path, 'plugin'))

        self.output_cxx = os.path.join(self.base_path, 'plugin/binding.cc')
        self.output_cxx_fp = open(self.output_cxx, 'w+')

        (shotname, extension) = os.path.splitext(os.path.basename(os.path.realpath(self.target)))
        self.output_js = os.path.join(self.base_path, 'plugin/%s.js' % shotname)
        # self.output_js_fp = open(self.output_js, 'w+')

        #########################################################################
        # node-gyp
        # self.generate_gyp()
        # fixed function and macro
        supplement = ''
        for content in self.supplement:
            supplement += (content + '\n')
        self.output_cxx_fp.write(template.bind_cxx_fixed % (supplement, self.register_content))

        # namespace
        self.generate_namespace()

        napi_init_declaration = ''
        napi_create_declaration = ''

        # value_objects
        for jstype in self.value_objects_order:
            instance = self.value_objects[jstype]
            # class declaration
            (napi_fun, napi_property) = self.generate_class_declaration(instance)
            # constructor implementation
            self.generate_constructor(instance)
            # property implementation
            self.generate_prop(instance)
            # napi declaration
            self.generate_napi_class_declaration(instance, napi_fun, napi_property)

            napi_init_declaration += '\t%s::Init(env, exports);\n' % instance['class_name']
            # napi_create_declaration += '\t\tNAPI_DECLARE_METHOD("createObject", %s::CreateObject),\n' % instance[
            #     'class_name']

        # class
        for instance in self.classes.values():
            # class declaration
            (napi_fun, napi_property) = self.generate_class_declaration(instance)
            # constructor implementation
            self.generate_constructor(instance)
            # function implementation
            self.generate_function(instance)
            # property implementation
            self.generate_prop(instance)
            # class function implementation
            self.generate_class_function(instance)
            # napi declaration
            self.generate_napi_class_declaration(instance, napi_fun, napi_property)

            napi_init_declaration += '\t%s::Init(env, exports);\n' % instance['class_name']
            # napi_create_declaration += '\t\tNAPI_DECLARE_METHOD("createObject", %s::CreateObject),\n' % instance[
            #     'class_name']

        # vector
        for instance in self.vectors.values():
            # class declaration
            (napi_fun, napi_property) = self.generate_class_declaration(instance)
            # constructor implementation
            self.generate_constructor(instance)
            # function implementation
            self.generate_vector_function(instance)
            # napi declaration
            self.generate_napi_class_declaration(instance, napi_fun, napi_property)

            napi_init_declaration += '\t%s::Init(env, exports);\n' % instance['class_name']

        # constant
        if self.constants:
            self.napi_declaration += '\t\t// constant\n'
            for constant in self.constants:
                self.napi_declaration += '\t\t{"%s", nullptr, nullptr, %s, nullptr, 0, napi_default, 0},\n' % (
                    constant.jsval, 'get_constant_' + constant.jsval)
                self.output_cxx_fp.write(template.constant_func % ('get_constant_' + constant.jsval, constant.cxxval))
        # array
        if self.value_arrays:
            self.napi_declaration += '\t\t// array\n'
            for arr in self.value_arrays.values():
                self.napi_declaration += '\t\tNAPI_DECLARE_METHOD("%s", generate_%s),\n' % (
                    arr['jstype'], arr['jstype'])
                self.output_cxx_fp.write(template.array_func % (arr['jstype'], arr['argc']))
        # global functions
        if self.global_functions:
            self.generate_global_functions()

        # vectors
        # self.generate_vectors()
        # global malloc
        self.napi_declaration += '\n\t\tNAPI_DECLARE_METHOD("_malloc", global_malloc)'
        self.output_cxx_fp.write(template.global_malloc)
        # napi declaration
        self.output_cxx_fp.write(template.napi_init.substitute(init=napi_init_declaration,
                                                               declaration=self.napi_declaration,
                                                               create_object=napi_create_declaration))

    def genfile_end(self):
        self.output_cxx_fp.close()
        # self.output_js_fp.close()
        if not self.supplemental_file_fp == None:
            self.supplemental_file_fp.close()

    def generate_gyp(self):
        self.output_gyp = os.path.join(self.base_path, 'plugin/binding.gyp')
        self.output_gyp_fp = open(self.output_gyp, 'w+')
        self.output_gyp_fp.write(template.bind_gyp %
                                 (os.path.relpath(self.output_cxx,
                                                  start=os.path.dirname(self.output_gyp)),
                                  os.path.relpath(self.target,
                                                  start=os.path.dirname(self.output_gyp))))
        self.output_gyp_fp.close()

    def generate_namespace(self):
        for namespace in self.namespace:
            self.output_cxx_fp.write('namespace %s {\n\n' % namespace)
            if self.supplemental_file:
                if namespace in self.supplemental_file:
                    for material in self.supplemental_file[namespace]:
                        self.output_cxx_fp.write('\t' + material + '\n')
            for meta_info in self.classes.values():
                for item in [meta_info['constructors'], meta_info['functions'], meta_info['properties'], meta_info['class_functions']]:
                    for overload_fun in item.values():
                        for spec_fun in overload_fun:
                            if not spec_fun == None and\
                                    not spec_fun[3] == None and\
                                    not spec_fun[2] == None and\
                                    not '<' in spec_fun[2] and\
                                    (namespace + '::') in spec_fun[2]:
                                self.output_cxx_fp.write('\t' + 'extern %s %s(%s);\n' % (
                                    spec_fun[0],
                                    spec_fun[2].split('::')[1],
                                    spec_fun[3]))
            for meta_info in self.value_objects.values():
                for item in [meta_info['properties']]:
                    for overload_fun in item.values():
                        for spec_fun in overload_fun:
                            if not spec_fun == None and\
                                    not spec_fun[3] == None and\
                                    not spec_fun[2] == None and\
                                    not '<' in spec_fun[2] and\
                                    (namespace + '::') in spec_fun[2]:
                                self.output_cxx_fp.write('\t' + 'extern %s %s(%s);\n' % (
                                    spec_fun[0],
                                    spec_fun[2].split('::')[1],
                                    spec_fun[3]))
            for overload_fun in self.global_functions.values():
                for spec_fun in overload_fun:
                    if not spec_fun == None and\
                            not spec_fun[3] == None and\
                            not spec_fun[2] == None and\
                            not '<' in spec_fun[2] and\
                            (namespace + '::') in spec_fun[2]:
                        self.output_cxx_fp.write('\t' + 'extern %s %s(%s);\n' % (
                            spec_fun[0],
                            spec_fun[2].split('::')[1],
                            spec_fun[3]))
            self.output_cxx_fp.write('\n}  // namespace %s\nusing namespace %s;\n' % (namespace, namespace))

    def parse_func_line(self, line, cxx_type, bool_static=False, getter=True):
        if line == None:
            return None
        searchObj = re.search(self.pattern, line)
        if searchObj:
            return_type = searchObj.group('return_type')
            args_list = searchObj.group('args_list').split(', ')
            fun_name = searchObj.group('fun_name')
            args_real = None
            if fun_name.split('::')[0] in self.namespace:
                if not bool_static:
                    del args_list[0]
                args_real = searchObj.group('args_list')
            if args_list == ['']:
                args_list = []
            return (return_type, args_list, fun_name, args_real)
        # only for raw property(public, no function)
        if getter:
            return (line.split(',')[0], [], None, line.split(',')[1])
        else:
            return ('void', [line.split(',')[0]], None, line.split(',')[1])

    def parse_class(self, classes):
        for obj in classes:
            meta_info = {}

            meta_info['cxxtype'] = obj.cxxtype
            meta_info['jstype'] = obj.jstype
            meta_info['class_name'] = 'class_' + obj.jstype

            constructors = self.parse_constructor(obj)
            functions = self.parse_function(obj)
            properties = self.parse_property(obj)
            class_function = self.parse_class_function(obj)

            meta_info['constructors'] = constructors
            meta_info['functions'] = functions
            meta_info['properties'] = properties
            meta_info['class_functions'] = class_function

            self.classes[obj.jstype] = meta_info

            # print '=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~= start'
            # print self.classes[obj.jstype].values()
            # print '=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~=~='

        self.register_content += template.register_class
        self.register_content += template.register_val

    def parse_constructor(self, obj):
        result = {'constructor': []}
        for constructor in obj.constructors:
            # print 'constructor arg types: %s\n' % constructor.cxxargtypes
            # print 'constructor cxxparams: %s\n' % constructor.cxxparams
            if constructor.cxxargtypes == None:
                fun_name = constructor.cxxparams.split(',')[0]
                if 'select_over' not in fun_name:
                    fun_name = self.supplemental_file[fun_name].encode("utf-8")
                searchObj = re.search(self.pattern, fun_name)
                if searchObj:
                    args_list = searchObj.group('args_list').split(', ')
                    if args_list == ['']:
                        args_list = []
                    result['constructor'].append(('%s *' % obj.cxxtype,
                                                  searchObj.group('args_list').split(', '),
                                                  searchObj.group('fun_name'),
                                                  searchObj.group('args_list')))
            else:
                args_list = constructor.cxxargtypes.split(', ')
                if args_list == ['']:
                    args_list = []
                result['constructor'].append(('%s *' % obj.cxxtype,
                                              args_list,
                                              'new %s' % obj.cxxtype,
                                              None))

        print '===========constructors=========='
        print result
        print ''
        return result

    def parse_function(self, obj):
        result = {}
        for function in obj.functions.items():
            js_method = function[0]
            result[js_method] = []
            for spec_fun in function[1]:
                fun_name = spec_fun[0]
                if 'select_over' not in fun_name:
                    fun_name = self.supplemental_file[fun_name].encode("utf-8")
                detail = self.parse_func_line(fun_name, obj.cxxtype)
                result[js_method].append(detail)
        print '===========functions=========='
        print result
        print ''
        return result

    def parse_property(self, obj):
        result = {}
        for prop in obj.properties.items():
            js_method = prop[0]
            result[js_method] = []
            prop_function = prop[1][0][0]
            if ',' in prop_function:
                # function (getter function, setter function)
                getter = prop_function.split(',')[0]
                if 'select_over' not in getter:
                    getter = self.supplemental_file[getter].encode("utf-8")
                setter = prop_function.split(',')[1]
                if 'select_over' not in setter:
                    setter = self.supplemental_file[setter].encode("utf-8")
            else:
                # member varible (setter = getter)
                setter = None
                print prop_function
                getter = self.supplemental_file[prop_function].encode("utf-8")
                if 'select_over' not in getter:
                    setter = getter

            result[js_method].append(self.parse_func_line(getter, obj.cxxtype))
            result[js_method].append(self.parse_func_line(setter, obj.cxxtype, getter=False))

        print '===========properties=========='
        print result
        print ''
        return result

    def parse_class_function(self, obj):
        result = {}
        for static_func in obj.class_functions.items():
            # print static_func
            js_method = static_func[0]
            result[js_method] = []
            for spec_fun in static_func[1]:
                detail = self.parse_func_line(spec_fun[0], obj.cxxtype, bool_static=True)
                result[js_method].append(detail)

        print '===========class functions=========='
        print result
        print ''
        return result

    def parse_arg_type(self, instance, arg):
        if arg in arg_template(['int', 'size_t', 'short', 'char']):
            return template.args_int
        if arg in arg_template(['unsigned int', 'unsigned short', 'unsigned char']):
            return template.args_uint
        if arg in arg_template(['intptr_t', 'long']):
            return template.args_long
        if arg in arg_template(['double', 'float']):
            return template.args_double
        if arg in arg_template(['std::string']):
            return template.args_string

        if not instance == None:
            cxx_type = instance['cxxtype'].split('::')
            if cxx_type[-1] in arg:
                return template.args_cxxtype % (instance['class_name'],
                                                instance['cxxtype'])

        searchObj = re.search('(const)\s*(.*)(&)', arg)
        if searchObj:
            arg = searchObj.group(2)
        searchObj = re.search('(.*)(&)', arg)
        if searchObj:
            arg = searchObj.group(1)

        for obj in self.classes.values():
            if arg.split('::')[-1] == obj['jstype'].split('::')[-1]:
                return template.args_cxxtype % (obj['class_name'],
                                                obj['cxxtype'])
        for obj in self.value_objects.values():
            if arg.split('::')[-1] == obj['jstype'].split('::')[-1]:
                i = 0
                fun = ''
                for prop in obj['properties'].items():
                    prop_name = prop[0]
                    prop_type = prop[1][0][0]
                    fun += '\tnapi_value output{0}_%s;\n' % (i)
                    fun += '\tnapi_get_named_property(env, args[{0}], "%s", &output{0}_%s);\n' % (prop_name, i)
                    if prop_type in ['float', 'double']:
                        fun += '\tnapi_get_value_double(env, output{0}_%s, (double *)&(p{0}->target()->%s));\n' % (
                            i, prop[1][1][3])
                    elif prop_type in ['int', 'size_t', 'short', 'char']:
                        fun += '\tnapi_get_value_int32(env, output{0}_%s, (int32_t *)&(p{0}->target()->%s));\n' % (
                            i, prop[1][1][3])
                    elif prop_type in ['unsigned int', 'unsigned short', 'unsgined char']:
                        fun += '\tnapi_get_value_uint32(env, output{0}_%s, (uint32_t *)&(p{0}->target()->%s));\n' % (
                            i, prop[1][1][3])
                    elif prop_type in ['bool']:
                        fun += '\tnapi_get_value_bool(env, output{0}_%s, &(p{0}->target()->%s));\n' % (i, prop[1][1][3])
                    else:
                        fun += '\tvoid *p{0}_%s = nullptr;\n\tnapi_get_value_external(env, output{0}_%s, &p{0}_%s);\n' % (
                            i, i, i)
                        fun += '\tp{0}->target()->%s = *((%s *)p{0}_%s);\n' % (prop[1][1][3], prop_type, i)
                    i += 1
                return template.args_obj % (obj['class_name'], obj['class_name'], fun, obj['cxxtype'])

        for arr in self.value_arrays.values():
            if arg.split('::')[-1] == arr['jstype'].split('::')[-1]:
                arr_args = ''
                args = ''
                for i in range(arr['argc']):
                    if arr['argtype'] == 'double':
                        arr_args += template.arr_args_double % (i, i, i, i, i, i)

                    args += 'arg{0}_%s' % i
                    if not i == arr['argc'] - 1:
                        args += ', '
                return template.args_array % (arr_args, arg, arg, args)
        for vec in self.vectors.values():
            if arg.split('::')[-1] == vec['cxxtype'].split('::')[-1]:
                return template.args_cxxtype % (vec['class_name'],
                                                vec['cxxtype'])
        print '------  parse_arg_type not supported type  ------'
        print arg

        return '\"parse_arg_type not supported type\"\n'

    def parse_return_type(self, instance, arg, cxx_value='res', napi_value='result', cxx_fun_name=None, arg_name=None):
        if arg == 'void':
            return template.return_void.substitute()
        if arg == 'bool':
            return template.return_bool.substitute(cxx_val=cxx_value, napi_val=napi_value)
        if arg in arg_template(['int', 'size_t', 'short', 'char']):
            return template.return_int.substitute(cxx_val=cxx_value, napi_val=napi_value)
        if arg in arg_template(['unsigned int', 'unsigned short', 'unsigned char']):
            return template.return_uint.substitute(cxx_val=cxx_value, napi_val=napi_value)
        if arg in arg_template(['intptr_t', 'long']):
            return template.return_long.substitute(cxx_val=cxx_value, napi_val=napi_value)
        if arg in arg_template(['float', 'double']):
            return template.return_double.substitute(cxx_val=cxx_value, napi_val=napi_value)
        if arg in arg_template(['std::string']):
            return template.return_string.substitute(cxx_val=cxx_value, napi_val=napi_value)

        if not instance == None:
            cxx_type = instance['jstype'].split('::')[-1]
            if cxx_type in arg:
                # return the class instance itself
                return template.return_class.substitute(cxx_val=cxx_value,
                                                        napi_val=napi_value,
                                                        class_domain='',
                                                        class_name=instance['class_name'])

        # return other class instance
        for obj in self.classes.values():
            if obj['jstype'].split('::')[-1] == arg.split('::')[-1]:
                return template.return_class.substitute(cxx_val=cxx_value,
                                                        napi_val=napi_value,
                                                        class_domain=obj['class_name'] + '::',
                                                        class_name=obj['class_name'])
        # return object
        for obj in self.value_objects.values():
            arg_type = arg.split('::')[-1]
            if arg_type == obj['jstype'].split('::')[-1]:
                fun = ''
                for prop in obj['properties'].items():
                    prop_name = prop[0]
                    prop_type = prop[1][0][0]
                    if not arg_name == None:
                        value_name = '%s_%s_val' % (arg_name, prop_name)
                    else:
                        value_name = '%s_val' % prop_name
                    fun += '\tnapi_value %s;\n' % value_name
                    if prop[1][0][2] == None:
                        get_val = cxx_value + '.' + prop[1][0][3]
                    else:
                        get_val = '%s(%s)' % (prop[1][0][2], cxx_value)

                    fun += self.parse_return_type(instance,
                                                  prop_type,
                                                  cxx_value=get_val,
                                                  napi_value=value_name,
                                                  arg_name=prop_name)

                    fun += '\tnapi_set_named_property(env, %s, "%s", %s);\n' % (napi_value, prop_name, value_name)
                return template.return_obj.substitute(napi_val=napi_value, obj_detail=fun)

        for arr in self.value_arrays.values():
            if arr['jstype'].split('::')[-1] == arg.split('::')[-1]:
                if arr['argtype'] == 'double':
                    return template.return_array.substitute(cxx_val=cxx_value,
                                                            napi_val=napi_value,
                                                            create_fun='napi_create_double')

        if arg.split('::')[-1] == 'val':
            # val is set to int defaultly
            val_type = 'int'
            if '<' in cxx_fun_name:
                searchObj = re.search('(<)(.*)(>)', cxx_fun_name)
                if searchObj:
                    val_type = searchObj.group(2)
            # array of basic type
            if val_type in ['char', 'unsigned char', 'short', 'unsigned short',
                            'int', 'unsigned int', 'float', 'double']:
                # print val_type
                return template.return_val_array.substitute(cxx_val=cxx_value,
                                                            napi_val=napi_value,
                                                            val_type=val_type,
                                                            array_type=template.arr_type[val_type])
            elif 'vector' in val_type:

                searchObj = re.search('(<)(.*)(>)', val_type)
                if searchObj:
                    val_type = searchObj.group(2)

                if val_type == 'float':
                    get_data = '\tfloat array_data = cursor->w[0].f;\n\tassert(array_data);\n'
                    get_data += '\tfloat &%s_data = array_data;\n' % (val_type.split('::')[-1])
                elif val_type == 'double':
                    get_data = '\tdouble array_data = cursor->d;\n\tassert(array_data);\n'
                    get_data += '\tdouble &%s_data = array_data;\n' % (val_type.split('::')[-1])
                else:
                    get_data = '\tvoid *array_data = (void *)cursor->w[0].p;\n\tassert(array_data);\n'
                    get_data += '\t%s &%s_data = *((%s *)array_data);\n' % (val_type,
                                                                            val_type.split('::')[-1], val_type)

                create_return_val = self.parse_return_type(instance,
                                                           val_type,
                                                           cxx_value='%s_data' % val_type.split('::')[-1],
                                                           napi_value=napi_value)
                return template.return_val_object.substitute(cxx_val=cxx_value,
                                                             val_type=val_type,
                                                             get_data=get_data,
                                                             create_return_val=create_return_val)

        print '------ parse_return_type not supported type ------'
        print arg
        return '\"parse_return_type not supported type\"\n'

    def generate_class_declaration(self, instance):
        napi_fun = ''
        declare_fun = '\t// function\n'
        if 'functions' in instance:
            for fun_name in instance['functions'].keys():
                napi_fun += '\t\tNAPI_DECLARE_METHOD("{0}", {0}),\n'.format(fun_name)
                declare_fun += '\tstatic napi_value %s(napi_env env, napi_callback_info info);\n' % fun_name

        napi_property = ''
        declare_property = '\t// property\n'
        if 'properties' in instance:
            for prop in instance['properties'].items():
                prop_name = prop[0]
                getter = 'get%s' % prop_name
                declare_property += '\tstatic napi_value %s(napi_env env, napi_callback_info info);\n' % getter
                if not prop[1][1] == None:
                    setter = 'set%s' % prop_name
                    declare_property += '\tstatic napi_value %s(napi_env env, napi_callback_info info);\n' % setter
                else:
                    setter = 'nullptr'
                napi_property += '\t\t{"%s", nullptr, nullptr, %s, %s, 0, napi_default, 0},\n' % (prop_name,
                                                                                                  getter,
                                                                                                  setter)

        declare_static_function = '\t// static_function\n'
        if 'class_functions' in instance:
            for fun_name in instance['class_functions'].keys():
                declare_static_function += '\tstatic napi_value %s(napi_env env, napi_callback_info info);\n' % fun_name
                self.napi_declaration += '\t\tNAPI_DECLARE_METHOD("{0}", {1}::{0}),\n'.format(fun_name,
                                                                                              instance['class_name'])

        self.output_cxx_fp.write(template.class_declaration.substitute(name=instance['class_name'],
                                                                       type=instance['cxxtype'],
                                                                       jstype=instance['jstype'],
                                                                       function=declare_fun,
                                                                       property=declare_property,
                                                                       class_function=declare_static_function))
        return (napi_fun, napi_property)

    def generate_napi_class_declaration(self, instance, napi_fun, napi_property):
        self.output_cxx_fp.write(template.fixed_class_function.substitute(name=instance['class_name'],
                                                                          type=instance['cxxtype'],
                                                                          jstype=instance['jstype'],
                                                                          declare_function=napi_fun,
                                                                          declare_property=napi_property))

    def generate_constructor(self, instance):
        self.output_cxx_fp.write('/*-------------------  constructor  -------------------*/\n')
        self.output_cxx_fp.write(template.constructor_func_start.substitute(name=instance['class_name'],
                                                                            type=instance['cxxtype']))
        for list_value in instance['constructors'].values():
            for cons_fun in list_value:
                self.output_cxx_fp.write('  case %d: {\n' % len(cons_fun[1]))

                argc = 0
                args = ''
                for i in range(len(cons_fun[1])):
                    arg_type = cons_fun[1][i]
                    # print arg_type
                    self.output_cxx_fp.write(self.parse_arg_type(instance, arg_type).format(i))
                    argc += 1
                    args += 'arg{0}'.format(i)
                    if not i == len(cons_fun[1]) - 1:
                        args += ', '
                self.output_cxx_fp.write('\tp = {0}({1});\n'.format(cons_fun[2], args))

                self.output_cxx_fp.write('  } break;\n')

        self.output_cxx_fp.write(template.constructor_func_end)

    def generate_function(self, instance):
        def detail(fun_name, args):
            if 'operator()' in fun_name:
                self.output_cxx_fp.write('\n\treturn (*obj)({0});\n'.format(args))
            elif not instance['cxxtype'] in fun_name:
                if args:
                    self.output_cxx_fp.write('\n\treturn {0}(*obj, {1});\n'.format(fun_name, args))
                else:
                    self.output_cxx_fp.write('\n\treturn {0}(*obj);\n'.format(fun_name))
            else:
                self.output_cxx_fp.write('\n\treturn obj->{0}({1});\n'.format(fun_name, args))

        self.output_cxx_fp.write('/*-------------------  function  -------------------*/\n')
        self.generate_function_detail(instance, instance['functions'], detail)

    def generate_function_detail(self, instance, functions, func_detail):
        for overload_fun in functions.items():
            js_fun_name = overload_fun[0]
            return_type = overload_fun[1][0][0]
            self.output_cxx_fp.write(template.function_detail_start % (return_type,
                                                                       js_fun_name,
                                                                       instance['cxxtype']))
            for spec_fun in overload_fun[1]:
                self.output_cxx_fp.write('  case %d: {\n' % len(spec_fun[1]))

                argc = 0
                args = ''
                arg_list = spec_fun[1]
                for i in range(len(arg_list)):
                    arg_type = arg_list[i]
                    self.output_cxx_fp.write(self.parse_arg_type(instance, arg_type).format(i))
                    argc += 1
                    args += 'arg{0}'.format(i)
                    if not i == len(arg_list) - 1:
                        args += ', '

                cxx_fun_name = spec_fun[2]

                func_detail(cxx_fun_name, args)

                self.output_cxx_fp.write('  } break;\n')

            self.output_cxx_fp.write(template.function_datail_end)

            if return_type == 'void':
                return_res = ''
            else:
                return_res = '%s res = ' % return_type

            cxx_fun_name = overload_fun[1][0][2]
            return_val = self.parse_return_type(instance,
                                                return_type,
                                                cxx_fun_name=cxx_fun_name)
            return_val = '\tnapi_value result;\n%s\n\treturn result;\n' % return_val

            self.output_cxx_fp.write(template.func_template.substitute(name=instance['class_name'],
                                                                       fun_name=overload_fun[0],
                                                                       type=instance['cxxtype'],
                                                                       return_res=return_res,
                                                                       return_val=return_val))

    def generate_prop(self, instance):
        self.output_cxx_fp.write('/*-------------------  property  -------------------*/\n')
        for prop in instance['properties'].items():
            # getter
            cxx_fun_name = prop[1][0][2]
            varbile = prop[1][0][3]
            return_type = prop[1][0][0]
            if cxx_fun_name == None:
                res = "%s res = %s;" % (return_type, 'target->%s' % varbile)
            elif instance['cxxtype'] in cxx_fun_name:
                res = "%s res = %s;" % (return_type, 'target->%s()' % cxx_fun_name)
            else:
                res = "%s res = %s;" % (return_type, '%s(*target)' % cxx_fun_name)

            return_val = self.parse_return_type(instance,
                                                return_type,
                                                cxx_fun_name=cxx_fun_name)
            return_val = '\tnapi_value result;\n%s\n\treturn result;\n' % return_val

            self.output_cxx_fp.write(template.prop_getter.substitute(fun_name='get%s' % prop[0],
                                                                     name=instance['class_name'],
                                                                     type=instance['cxxtype'],
                                                                     return_fun=res,
                                                                     return_val=return_val))
            # setter
            if not prop[1][1] == None:
                arg = prop[1][1][1][0]
                res = self.parse_arg_type(instance, arg).format(0)
                cxx_fun_name = prop[1][1][2]
                varbile = prop[1][1][3]
                if cxx_fun_name == None:
                    fun = '    target->%s = arg0;' % varbile
                elif instance['cxxtype'] in cxx_fun_name:
                    fun = '    target->%s(arg0);' % cxx_fun_name
                else:
                    fun = '    %s(*target, arg0);' % cxx_fun_name

                self.output_cxx_fp.write(template.prop_setter.substitute(fun_name='set%s' % prop[0],
                                                                         name=instance['class_name'],
                                                                         type=instance['cxxtype'],
                                                                         res=res,
                                                                         fun=fun))

    def generate_class_function(self, instance):
        def detail(fun_name, args):
            if not instance['cxxtype'] in fun_name:
                self.output_cxx_fp.write('\n\treturn {0}({1});\n'.format(fun_name, args))
            else:
                self.output_cxx_fp.write('\n\treturn {0}({1});\n'.format(fun_name, args))

        self.output_cxx_fp.write('/*-------------------  class function  -------------------*/\n')
        self.generate_function_detail(instance, instance['class_functions'], detail)

    # -------------------constant---------------------------
    def parse_constant(self, constants):
        self.register_content += template.register_constant
        self.constants = constants

    # -------------------objects----------------------------
    def parse_objects(self, objects):
        self.register_content += template.register_object
        self.value_objects_order = []
        only_default_constructor = [fun.encode("utf-8") for fun in self.supplemental_file['only_default_constructor']]
        for obj in objects:
            # if not obj.jstype=='Size':
            #     continue
            self.value_objects_order.append(obj.jstype)
            self.value_objects[obj.jstype] = {'jstype': obj.jstype,
                                              'cxxtype': obj.cxxtype,
                                              'class_name': 'object_' + obj.jstype,
                                              'constructors': {'constructor': [(obj.cxxtype + ' *',
                                                                                [],
                                                                                'new ' + obj.cxxtype,
                                                                                None)]},
                                              'properties': {}}

            properties = self.value_objects[obj.jstype]['properties']
            filed_type = []
            for field in obj.field_arr:
                prop_name = field[0]
                properties[prop_name] = []
                getter = field[1]
                setter = field[2]
                if 'select_over' not in getter:
                    getter = self.supplemental_file[getter].encode("utf-8")
                if not setter == None:
                    if 'select_over' not in setter:
                        setter = self.supplemental_file[setter].encode("utf-8")
                elif ',' in getter:
                    # member varible (getter=setter)
                    setter = getter

                properties[prop_name].append(self.parse_func_line(getter, obj.cxxtype))
                properties[prop_name].append(self.parse_func_line(setter, obj.cxxtype, getter=False))
                filed_type.append(properties[prop_name][0][0])
            if not obj.jstype in only_default_constructor:
                self.value_objects[obj.jstype]['constructors']['constructor'].append((obj.cxxtype + ' *',
                                                                                      filed_type,
                                                                                      'new ' + obj.cxxtype,
                                                                                      None))
            # print obj.jstype
            # print properties
            # print ''
            # if obj.jstype == 'Exception':
            #     print self.value_objects[obj.jstype]
            # print self.value_objects[obj.jstype]
            # print obj.jstype
            # print obj.cxxtype
            # print obj.field_arr
        print '===========objects=========='
        print self.value_objects.values()
        print ''

    # -------------------arrays----------------------------
    def parse_arrays(self, arrays):
        self.register_content += template.register_array
        for arr in arrays:
            arg_type = arr.cxxtype
            # print arr.jstype
            if '<' in arr.cxxtype:
                searchObj = re.search('(<)(.*)(>)', arr.cxxtype)
                if searchObj:
                    arg_type = searchObj.group(2)

            self.value_arrays[arr.jstype] = {'jstype': arr.jstype,
                                             'cxxtype': arr.cxxtype,
                                             'argc': len(arr.elem_arr),
                                             'argtype': arg_type}
        print '===========arrays=========='
        print self.value_arrays
        print ''

    # -------------------functions----------------------------
    def parse_global_functions(self, functions):
        self.register_content += template.register_func
        for func in functions:
            js_method = func.js_func
            if self.global_functions.get(js_method) == None:
                self.global_functions[js_method] = []
            fun_name = func.cxx_funcs_policies
            if 'select_over' not in fun_name:
                fun_name = self.supplemental_file[fun_name].encode("utf-8")
            detail = self.parse_func_line(fun_name, '', bool_static=True)
            self.global_functions[js_method].append(detail)
        print '===========global functions=========='
        print self.global_functions
        print ''

    def generate_global_functions(self):
        self.napi_declaration += '\t\t// global functions\n'
        for func in self.global_functions.items():
            js_method = func[0]
            return_type = func[1][0][0]
            overload_fun = func[1]
            self.napi_declaration += '\t\tNAPI_DECLARE_METHOD("%s", global_%s),\n' % (js_method, js_method)
            self.output_cxx_fp.write(template.global_func_start.substitute(fun_name='global_' + js_method,
                                                                           return_type=return_type))
            for spec_fun in overload_fun:

                self.output_cxx_fp.write('  case %d: {\n' % len(spec_fun[1]))

                argc = 0
                args = ''
                arg_list = spec_fun[1]
                for i in range(len(arg_list)):
                    arg_type = arg_list[i]
                    self.output_cxx_fp.write(self.parse_arg_type(None, arg_type).format(i))
                    argc += 1
                    args += 'arg{0}'.format(i)
                    if not i == len(arg_list) - 1:
                        args += ', '

                cxx_fun_name = spec_fun[2]
                self.output_cxx_fp.write('\treturn %s(%s);\n' % (cxx_fun_name, args))

                self.output_cxx_fp.write('  } break;\n')

            if return_type == 'void':
                return_res = ''
            else:
                return_res = '%s res = ' % return_type

            cxx_fun_name = func[1][0][2]
            return_val = self.parse_return_type(None,
                                                return_type,
                                                cxx_fun_name=cxx_fun_name)
            return_val = '\tnapi_value result;\n%s\n\treturn result;\n' % return_val

            # print return_val

            self.output_cxx_fp.write(template.global_func_end.substitute(fun_name='global_' + js_method,
                                                                         return_val=return_val,
                                                                         return_res=return_res))
            # import sys
            # sys.exit(1)

    # -------------------vectors----------------------------
    def parse_vectors(self, vectors):
        for vec in vectors:
            self.vectors[vec.jstype] = {'jstype': vec.jstype,
                                        'cxxtype': vec.class_.cxxtype,
                                        'class_name': 'vec' + vec.jstype,
                                        'constructors': {'constructor': [('%s *' % vec.class_.cxxtype,
                                                                          [],
                                                                          'new %s' % vec.class_.cxxtype,
                                                                          None)]}
                                        }
            fun_list = {}
            cxx_fun_name = vec.class_.functions['get'][0][0].lstrip('&')
            fun_list['get'] = [('val', ['size_t'], cxx_fun_name, None)]

            cxx_fun_name = vec.class_.functions['set'][0][0].lstrip('&')
            fun_list['set'] = [('bool', ['size_t', 'const %s&' % vec.cxxelemtype], cxx_fun_name, None)]

            cxx_fun_name = vec.class_.functions['push_back'][0][0].lstrip('&')
            fun_list['push_back'] = [('void', ['const %s&' % vec.cxxelemtype], cxx_fun_name, None)]

            cxx_fun_name = vec.class_.functions['resize'][0][0].lstrip('&')
            fun_list['resize'] = [('void', ['size_t'], cxx_fun_name, None)]

            cxx_fun_name = vec.class_.functions['size'][0][0].lstrip('&')
            fun_list['size'] = [('size_t', [], cxx_fun_name, None)]

            self.vectors[vec.jstype]['functions'] = fun_list

        print '===========vectors=========='
        print self.vectors
        print ''

    def generate_vector_function(self, instance):
        def detail(fun_name, args):
            if 'emscripten::internal::VectorAccess' in fun_name:
                self.output_cxx_fp.write('\n\treturn {0}(*obj, {1});\n'.format(fun_name, args))
            else:
                self.output_cxx_fp.write('\n\treturn obj->{0}({1});\n'.format(fun_name, args))

        self.output_cxx_fp.write('/*-------------------  function  -------------------*/\n')
        self.generate_function_detail(instance, instance['functions'], detail)
