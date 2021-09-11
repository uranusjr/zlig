#include <Python.h>

static PyObject* add(PyObject* self, PyObject* args) {
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a+b);
}

static PyMethodDef HelloMethods[] = {
    {"add", (PyCFunction)add, METH_VARARGS, "Add two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "demo.demo",
    "Minimal C module.",
    -1,
    HelloMethods,
};

PyMODINIT_FUNC
PyInit_demo(void) {
    return PyModule_Create(&moduledef);
}
