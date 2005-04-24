from interfaces import *
from api import *
import declarative
try:
    import protocols
except ImportError:
    import dummy_protocols as protocols

class SchemaMeta(declarative.DeclarativeMeta):

    """
    Takes a class definition, and puts all the validators it finds
    into a class variable (fields).  Also makes sure that this class
    variable is unique to this class (i.e., is not shared by
    subclasses), as it also does for chained_validators and
    pre_validators.
    """

    def __new__(meta, class_name, bases, d):
        cls = declarative.DeclarativeMeta.__new__(meta, class_name, bases, d)
        # Don't bother doing anything if this is the most parent
        # Schema class (which is the only class with just
        # FancyValidator as a superclass):
        if bases == (FancyValidator,):
            return cls
        # Make sure we have out own copy of fields,
        # not shared by parent classes (and indirectly not by
        # children either).  
        cls.fields = cls.fields.copy()
        cls.chained_validators = cls.chained_validators[:]
        cls.pre_validators = cls.pre_validators[:]
        # Scan through the class variables we've defined *just*
        # for this subclass, looking for validators (both classes
        # and instances):
        for key, value in d.items():
            if key in ['pre_validators', 'chained_validators',
                       'view']:
                continue
            validator = adapt_validator(value)
            if validator:
                cls.fields[key] = value
                delattr(cls, key)
            # This last case means we're overwriting a validator
            # from a superclass:
            elif cls.fields.has_key(key):
                del cls.fields[key]
        for name, value in cls.fields.items():
            cls.add_field(name, value)
        return cls

class Schema(FancyValidator):

    """
    A schema validates a dictionary of values, applying different
    validators (be key) to the different values.  If
    allow_extra_fields=True, keys without validators will be allowed;
    otherwise they will raise Invalid. If filter_extra_fields is
    set to true, then extra fields are not passed back in the results.

    Validators are associated with keys either with a class syntax, or
    as keyword arguments (class syntax is usually easier).  Something
    like::

        class MySchema(Schema):
            name = Validators.PlainText()
            phone = Validators.PhoneNumber()

    These will not be available as actual instance variables, but will
    be collected in a dictionary.  To remove a validator in a subclass
    that is present in a superclass, set it to None, like::

        class MySubSchema(MySchema):
            name = None
    """

    __metaclass__ = SchemaMeta

    protocols.advise(
        instancesProvide=[ISchema])

    chained_validators = []
    pre_validators = []
    allow_extra_fields = False
    filter_extra_fields = False
    compound = True
    fields = {}
    order = []

    messages = {
        'notExpected': 'The input field %(name)s was not expected.',
        'missingValue': "Missing value",
        }
    
    def _to_python(self, value_dict, state):
        if not value_dict and self.if_empty is not NoDefault:
            return self.if_empty
        
        for validator in self.pre_validators:
            value_dict = to_python(validator, value_dict, state)
        
        new = {}
        errors = {}
        unused = self.fields.keys()
        if state is not None:
            previous_key = getattr(state, 'key', None)
            previous_full_dict = getattr(state, 'full_dict', None)
            state.full_dict = value_dict
        try:
            for name, value in value_dict.items():
                try:
                    unused.remove(name)
                except ValueError:
                    if not self.allow_extra_fields:
                        raise Invalid(
                            self.message('notExpected', state,
                                         name=repr(name)),
                            value_dict, state)
                    else:
                        if not self.filter_extra_fields:
                            new[name] = value
                        continue
                validator = adapt_validator(self.fields[name], state)

                try:
                    new[name] = validator.to_python(value, state)
                except Invalid, e:
                    errors[name] = e

            for name in unused:
                validator = adapt_validator(self.fields[name], state)
                try:
                    if_missing = validator.if_missing
                except AttributeError:
                    if_missing = NoDefault
                if if_missing is NoDefault:
                    errors[name] = Invalid(
                        self.message('missingValue', state),
                        None, state)
                else:
                    new[name] = validator.if_missing

            if errors:
                raise Invalid(
                    format_compound_error(errors),
                    value_dict, state,
                    error_dict=errors)

            for validator in self.chained_validators:
                new = to_python(validator, new, state)

            return new

        finally:
            if state is not None:
                state.key = previous_key
                state.full_dict = previous_full_dict

    def _from_python(self, value_dict, state):
        chained = self.chained_validators[:]
        chained.reverse()
        finished = []
        for validator in chained:
            __traceback_info__ = 'for_python chained_validator %s (finished %s)' % (validator, ', '.join(map(repr, finished)) or 'none')
            finished.append(validator)
            value_dict = from_python(validator, value_dict, state)
        new = {}
        errors = {}
        unused = self.fields.keys()
        if state is not None:
            previous_key = getattr(state, 'key', None)
            previous_full_dict = getattr(state, 'full_dict', None)
            state.full_dict = value_dict
        try:
            for name, value in value_dict.items():
                __traceback_info__ = 'for_python in %s' % name
                try:
                    unused.remove(name)
                except ValueError:
                    if not self.allow_extra_fields:
                        raise Invalid(
                            self.message('notExpected', state,
                                         name=repr(name)),
                            value_dict, state)
                    if not self.filter_extra_fields:
                        new[name] = value
                else:
                    try:
                        new[name] = from_python(self.fields[name],
                                                value, state)
                    except Invalid, e:
                        errors[name] = e

            del __traceback_info__

            for name in unused:
                validator = adapt_validator(self.fields[name], state)
                try:
                    new[name] = validator.from_python(None, state)
                except Invalid, e:
                    errors[name] = e

            if errors:
                raise Invalid(
                    format_compound_error(errors),
                    value_dict, state,
                    error_dict=errors)

            pre = self.pre_validators[:]
            pre.reverse()
            for validator in pre:
                __traceback_info__ = 'for_python pre_validator %s' % validator
                new = from_python(validator, new, state)

            return new
            
        finally:
            if state is not None:
                state.key = previous_key
                state.full_dict = previous_full_dict
            


    def add_chained_validator(self, cls, validator):
        if self is not None:
            if self.chained_validators is cls.chained_validators:
                self.chained_validators = cls.chained_validators[:]
            self.chained_validators.append(validator)
        else:
            cls.chained_validators.append(validator)

    add_chained_validator = declarative.classinstancemethod(
        add_chained_validator)

    def add_field(self, cls, name, validator):
        if self is not None:
            if self.fields is cls.fields:
                self.fields = cls.fields.copy()
            self.fields[name] = validator
        else:
            cls.fields[name] = validator

    add_field = declarative.classinstancemethod(add_field)

    def add_pre_validator(self, cls, validator):
        if self is not None:
            if self.pre_validators is cls.pre_validators:
                self.pre_validators = cls.pre_validators[:]
            self.pre_validators.append(validator)
        else:
            cls.pre_validators.append(validator)

    add_pre_validator = declarative.classinstancemethod(add_pre_validator)


def format_compound_error(v, indent=0):
    if isinstance(v, Exception):
        return str(v)
    elif isinstance(v, dict):
        l = v.items()
        l.sort()
        return ('%s\n' % (' '*indent)).join(
            ["%s: %s" % (k, format_compound_error(value, indent=len(k)+2))
             for k, value in l
             if value is not None])
    elif isinstance(v, list):
        return ('%s\n' % (' '*indent)).join(
            ['%s' % (format_compound_error(value, indent=indent))
             for value in v
             if value is not None])
    elif isinstance(v, str):
        return v
    else:
        assert 0, "I didn't expect something like %s" % repr(v)
        
